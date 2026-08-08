import sys

# Install missing dependencies
from pip._internal import main as pip_main

pip_main(['install', 'python-dotenv'])
