import re
from setuptools import setup, find_packages

# Read version from __init__.py WITHOUT importing the package.
# The old code did "from wati_integration import __version__" which fails
# during fresh pip install because the package is not on sys.path yet.
# This regex approach works at any point in the install lifecycle.
with open("wati_integration/__init__.py") as f:
    version = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', f.read()).group(1)

with open("requirements.txt") as f:
    install_requires = [
        line.strip()
        for line in f.read().splitlines()
        if line.strip() and not line.startswith("#")
    ]

setup(
    name="wati_integration",
    version=version,
    description="WATI WhatsApp Integration for ERPNext / Frappe v14, v15, v16",
    author="Bhavesh Maheshwari",
    author_email="iambhavesh95863@gmail.com",
    url="https://github.com/bhavesh95863/wati_integration",
    packages=find_packages(),
    zip_safe=False,
    include_package_data=True,
    install_requires=install_requires,
    python_requires=">=3.10",
)
