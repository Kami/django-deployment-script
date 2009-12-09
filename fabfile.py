# -*- coding: utf-8 -*-
#
# Name: Fabric deployment script for Django applications
# Description: Fabric script for deploying your Django applications
# to one or more remote servers.
# Author: Tomaž Muraus (http://www.tomaz-muraus.info)
# Based on: Gareth Rushgrove deployment script (http://morethanseven.net/2009/07/27/fabric-django-git-apache-mod_wsgi-virtualenv-and-p/)
# Version: 1.0
# License: GPL

# Requirements:
# - Windows / Linux / Mac OS
# - Python >= 2.6 (< 3.0)
# - Fabric Python library - tested with 0.9 (http://docs.fabfile.org/0.9.0/)
#
# Your project directory structure could look something like this:
# 
# project_name/
#    app1/
#        __init__.py
#        admin.py
#        models.py
#        tests.py
#        ....
#    app2/
#        __init__.py
#        admin.py
#        ...
#    __init__.py
#    manage.py
#    settings.py
#    urls.py
#    ...
# other/
#    project_name.apache
#    project_name.lighttpd
#    project_name.wsgi
#    settings.py
#
# And then you would deploy your application by following this steps:
#
# 1. fab <environment> setup - creates a new Python virtual environment and folders for your application
# 2. fab <environment> install_django_from_svn - downloads the latest Django copy from SVN and creates a symbolic link to site-packages*
# 3. fab <environment> deploy_site - deploys your application**
# 4. fab <environment> deploy_database - imports your database data which is located in other/<db_file>
#
# * If you want to use the latest stable version of Django, skip the step number 2 and add "Django" to your dependencies.txt file
#
# ** "deploy_site" runs the following tasks:
#
# 1. Downloads the latest version of you application from local Git repository
# 2. Installs the modules required by your application (listed in other/dependencies.txt)
# 3. Uploads the latest version of the code to your production server(s), creates a symbolic link for the current release
#    and adds Apache and lighttpd vhost
# 4. Creates the database schema (syncdb)
# 5. Reloads the Apache and lighttpd server

# Notes:
#
# This is not really a generic deployment script because most of the paths are "hard-coded" and
# it makes a lot of assumptions about your local and remote environment(s):
#
# - you use Apache and mod_wsgi for serving the Django application,
# - lighttpd for serving static files
# - MySQL database server
# - dependencies for your application are stored in other/dependencies.txt
# - production settings file is named settings.py and stored in directory other/
# - Apache vhost file is named <project name>.apache and stored in directory other/
# - lighttpd vhost file is named <project name>.lighttpd and stored in directory other/
# - mod_wsgi bootstrap script is named <project name>.wsgi and stored in directory other/
# - database dump is named <db_file> and stored in directory other/

import os
import sys
import posixpath

from fabric.api import env, local, run, sudo, put, cd, runs_once, prompt, require, settings
from fabric.contrib.files import exists, upload_template
from fabric.contrib.console import confirm
from fabric.context_managers import hide

# Global settings
env.project_name = 'project_name' # Project name
env.project_domain = 'yourdomain.com' # Project domain
env.project_directory = '/home/your/account/projects/project_name/src' # Local project working directory

# Environments
def production():
    "Production environment"
    
    # General settings
    env.hosts = ['88.88.88.88:4444'] # One or multiple server addresses in format ip:port
    env.path = '/path/to/your/app' # Path where your application will be deployed
    env.user = 'deploy' # Username used when making SSH connections
    env.www_user = 'www' # User account under which Apache is running
    env.password = 'blahblahblah' # Connection and sudo password (you can omit it and Fabric will prompt you when necessary)
    env.shell = '/usr/local/bin/bash -l -c' # Path to your shell binary
    env.sudo_prompt = 'Password:' # Sudo password prompt
    
    # Database settings
    env.db_hostname = 'localhost'
    env.db_username = 'project_name'
    env.db_password = 'blahblahblah'
    env.db_name = 'project_name_page'
    env.db_file = 'db_dump.sql'

# Tasks
def run_tests():
    "Run the test suite"
    
    local('python %(project_name)s/manage.py test' % {'project_name': env.project_name})
    
def get_django_from_svn():
    "Download the latest Django release from SVN"
    require('path')
        
    run('cd %(path)s; svn co http://code.djangoproject.com/svn/django/trunk/ django-trunk' % {'path': env.path})
    run('ln -s %(path)s/django-trunk/django %(path)s/lib/python2.6/site-packages/django' % {'path': env.path})
    
def update_django_from_svn():
    "Update the local Django SVN release"
    require('path')
        
    sudo('cd %(path)s/django-trunk; svn update' % {'path': env.path})

def setup():
    "Create a new Python virtual environment and folders where our application will be saved"
    require('hosts', provided_by = [production])
    require('path')
    
    sudo('easy_install pip')
    sudo('pip install virtualenv')
    sudo('mkdir -p %(path)s; cd %(path)s; virtualenv --no-site-packages .'  % {'path': env.path})
    sudo('chown -R %(user)s:%(user)s %(path)s'  % {'user': env.user, 'path': env.path})
    run('cd %(path)s; mkdir releases; mkdir packages' % {'path': env.path})

def deploy_site():
    """
    Deploy the latest version of the site to the server(s), install any
    required third party modules, install the virtual hosts and 
    then reload the Apache and lighttpd
    """
    require('hosts', provided_by = [production])
    require('path')

    import time
    env.release = time.strftime('%Y%m%d%H%M%S')

    _upload_archive_from_git()
    _install_dependencies()
    _install_site()
    _symlink_current_release()
    _create_database_schema()
    _reload_apache()
    _reload_lighttpd()
    
def deploy_database():
    """
    Deploy the database (import data located in db_file)
    """
    require('db_hostname', 'db_username', 'db_password', 'db_name', 'db_file')
    require('release', provided_by = [deploy_site, setup])
    
    run('mysql -h %(db_hostname)s -u %(db_username)s -p%(db_password)s %(db_name)s < %(path)s/releases/%(release)s/other/%(db_file)s' % {'path': env.path, 'release': env.release, 'db_hostname': env.db_hostname, 'db_username': env.db_username, 'db_password': env.db_password, 'db_name': env.db_name, 'db_file': env.db_file})
    run('rm %(path)s/releases/%(release)s/other/%(db_file)s' % {'path': env.path, 'release': env.release, 'db_file': env.db_file})
    
def deploy_release(release):
    "Specify a specific release to be made live"
    require('hosts', provided_by = [production])
    require('path')
    
    env.release = release
    run('cd %(path)s; rm releases/previous; mv releases/current releases/previous;'  % {'path': env.path})
    run('cd %(path)s; ln -s %(release)s releases/current'  % {'path': env.path, 'release': env.release})
    
    _reload_apache()

def rollback():
    """
    Limited rollback capability. Simple loads the previously current
    version of the code. Rolling back again will swap between the two.
    """
    require('hosts', provided_by = [production])
    require('path')

    run('cd %(path)s; mv releases/current releases/_previous;' % {'path': env.path})
    run('cd %(path)s; mv releases/previous releases/current;' % {'path': env.path})
    run('cd %(path)s; mv releases/_previous releases/previous;' % {'path': env.path})
    
    _reload_apache()
    
def cleanup():
    """
    Clean up the remote environment.
    Flush the database, delete the Apache and lighttpd vhosts, uninstall
    installed dependencies and remove everything from directory packages, releases and other
    """
    
    with settings(hide('warnings', 'stderr', 'stdout'), warn_only = True):
        # Flush the database
        run('cd %(path)s/releases/current/%(project_name)s; ../../../bin/python manage.py flush --noinput' % {'path': env.path, 'project_name': env.project_name})
        
        # Delete the Apache and lighttpd vhost config files
        sudo('rm /usr/local/etc/apache22/sites-available/%(project_domain)s'  % {'project_domain': env.project_domain})
        sudo('rm /usr/local/etc/apache22/sites-enabled/%(project_domain)s' % {'project_domain': env.project_domain})
        sudo('rm /usr/local/etc/lighttpd/%(project_domain)s.conf' % {'project_domain': env.project_domain})
        
        # Remove the include statement from the lighttpd config file for our vhost
        sudo('sed \'/\/usr\/local\/etc\/lighttpd\/%(project_domain)s.conf/d\' /usr/local/etc/lighttpd.conf > /usr/local/etc/lighttpd.conf.1; mv /usr/local/etc/lighttpd.conf.1 /usr/local/etc/lighttpd.conf' % {'project_domain': env.project_domain})
     
        # Uninstall installed dependencies
        run('cd %(path)s; pip uninstall -E . -r ./releases/current/dependencies.txt -y' % {'path': env.path})
        
        # Remove directory packages, releases and other (if exists)
        sudo('rm -rf %(path)s/packages/'  % {'path': env.path})
        sudo('rm -rf %(path)s/releases/' % {'path': env.path})
        sudo('rm -rf %(path)s/other/' % {'path': env.path})
    
# Helpers - these are called by other functions rather than directly
def _upload_archive_from_git():
    "Create an archive from the current Git master branch and upload it"
    require('release', provided_by = [deploy_site, setup])
    
    local('git archive --format=zip master > %(release)s.zip' % {'release': env.release})
    run('mkdir %(path)s/releases/%(release)s' % {'path': env.path, 'release': env.release})
    put('%(release)s.zip' % {'release': env.release}, '%(path)s/packages/' % {'path': env.path})
    run('cd %(path)s/releases/%(release)s && tar zxf ../../packages/%(release)s.zip' % {'path': env.path, 'release': env.release})
    local('rm %(release)s.zip' % {'release': env.release})

def _install_site():
    "Add the virtualhost to Apache and lighttpd and move the production settings config file"
    require('release', provided_by = [deploy_site, setup])
    
    # Move files to their final desination
    run('cd %(path)s/releases/%(release)s; mv other/dependencies.txt dependencies.txt' % {'path': env.path, 'release': env.release})
    run('cd %(path)s/releases/%(release)s; mv other/%(project_name)s.wsgi %(project_name)s/%(project_name)s.wsgi' % {'path': env.path, 'release': env.release, 'project_name': env.project_name})
    
    # Apache
    sudo('cd %(path)s/releases/%(release)s; cp other/%(project_name)s.apache /usr/local/etc/apache22/sites-available/%(project_domain)s' % {'path': env.path, 'release': env.release, 'project_name': env.project_name, 'project_domain': env.project_domain})
    sudo('ln -s /usr/local/etc/apache22/sites-available/%(project_domain)s /usr/local/etc/apache22/sites-enabled/%(project_domain)s' % {'project_domain': env.project_domain, 'project_name': env.project_name}) 
    
    # Lighttpd
    sudo('cd %(path)s/releases/%(release)s; cp other/%(project_name)s.lighttpd /usr/local/etc/lighttpd/%(project_domain)s.conf' % {'path': env.path, 'release': env.release, 'project_name': env.project_name, 'project_domain': env.project_domain})
 
    # There are some problems with quote escaping in sudo, run and local functions, so we first store a line which will be appended to the config in a local file
    # and later on remove the added backslashes from the lighttpd config file
    local('echo include "/usr/local/etc/lighttpd/%(project_domain)s.conf" >> vhost_file_path.tmp' % {'project_domain': env.project_domain})
    put('vhost_file_path.tmp', '%(path)s/vhost_file_path.tmp' % {'path': env.path})
    local('rm vhost_file_path.tmp')
    
    sudo('cd %(path)s; cat vhost_file_path.tmp >> /usr/local/etc/lighttpd.conf; rm vhost_file_path.tmp' % {'path': env.path})
    sudo('sed \'s/\\\//g\' /usr/local/etc/lighttpd.conf > /usr/local/etc/lighttpd.conf.1; mv /usr/local/etc/lighttpd.conf.1 /usr/local/etc/lighttpd.conf')
    
    # Move the production settings.py file
    sudo('cd %(path)s/releases/%(release)s/other; mv settings.py %(path)s/releases/%(release)s/%(project_name)s/settings.py' % {'path': env.path, 'release': env.release, 'project_name': env.project_name})
    
    run('cd %(path)s/releases/%(release)s; rm -rf other/' % {'path': env.path, 'release': env.release})
    sudo('chown -R %(www_user)s:%(www_user)s %(path)s/releases/%(release)s' % {'www_user': env.www_user, 'path': env.path, 'release': env.release})

def _install_dependencies():
    "Install the required packages from the requirements file using PIP" 
    require('release', provided_by = [deploy_site, setup])

    run('cd %(path)s; pip install -E . -r ./releases/%(release)s/other/dependencies.txt' % {'path': env.path, 'release': env.release})

def _symlink_current_release():
    "Symlink our current release"
    require('release', provided_by = [deploy_site, setup])

    # Don't print warrnings if there is no current release
    with settings(hide('warnings', 'stderr'), warn_only = True):
        run('cd %(path)s; rm releases/previous; mv releases/current releases/previous' % {'path': env.path }) 
    
    run('cd %(path)s; ln -s %(release)s releases/current' % {'path': env.path, 'release': env.release})
    
def _create_database_schema():
    "Create the database tables for all apps in INSTALLED_APPS whose tables have not already been created"
    require('project_name')
    
    run('cd %(path)s/releases/current/%(project_name)s; ../../../bin/python manage.py syncdb --noinput' % {'path': env.path, 'project_name': env.project_name})

def _reload_apache():
    "Reload the apache server"
    sudo('/usr/local/etc/rc.d/apache22 reload')

def _reload_lighttpd():
    "Reload the lighttpd server"
    sudo('/usr/local/etc/rc.d/lighttpd reload')