from setuptools import setup, find_packages

with open("requirements.txt") as f:
    install_requires = f.read().strip().split("\n")

version_ns = {}
with open("dux_cybervidya/__init__.py") as f:
    exec(f.read(), version_ns)

setup(
    name="dux_cybervidya",
    version=version_ns["__version__"],
    description="ERPNext receiver for CyberVidya end-of-day fee collection.",
    author="Dux DigiTech",
    author_email="aditya@duxdigitech.com",
    packages=find_packages(),
    zip_safe=False,
    include_package_data=True,
    install_requires=install_requires,
)
