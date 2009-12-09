import os
import sys
import django.core.handlers.wsgi

# put the Django project on sys.path
root_path = os.path.abspath(os.path.dirname(__file__) + '../')
sys.path.insert(0, os.path.join(root_path, 'project_name'))
sys.path.insert(0, root_path)

os.environ['DJANGO_SETTINGS_MODULE'] = 'project_name.settings'

application = django.core.handlers.wsgi.WSGIHandler()