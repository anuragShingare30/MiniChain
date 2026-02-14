from setuptools import setup, find_packages

setup(
    name="minichain",
    version="0.1.0",
    packages=find_packages(),
    py_modules=["main"],
    install_requires=[
        "pynacl==1.6.2",
        "libp2p==0.5.0",  # Fixed: was "py-libp2p"
    ],
    entry_points={
        "console_scripts": [
            "minichain=main:main",  # Requires main() function in main.py
        ],
    },
    python_requires=">=3.8",
)
