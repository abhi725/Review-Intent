# Exists so that `pytest` and `python -m pytest` behave the same way.
#
# `python -m pytest` puts the current directory on sys.path; the `pytest`
# console script does not. With no conftest.py and no ini file at the root,
# nothing else put this directory there either, so every test module failed to
# collect with `ModuleNotFoundError: No module named 'intentdesk'` — but only
# when run the first way, which is the way a stranger to the repository runs it.
#
# In pytest's default "prepend" import mode the directory holding the
# rootmost conftest.py is inserted into sys.path, so the file needs no contents
# to do its job. Do not delete it for being empty.
