python3 -m venv venv
. venv/bin/activate
pip install pip-tools
pip-compile -o pypi.lock pypi.txt
deactivate
rm -rf venv