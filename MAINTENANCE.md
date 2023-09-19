# Build
Building the distributable package for Pypi consists of:
`python -m build` 

Uploading to Pypi can be done using `twine upload dist/*`. When asked for a username use `__token__` and supply an API token as password.

# Documentation
Documentation is generated using Sphinx. Run `make html` inside the `docs` folder to generate the documentation.
