from setuptools import setup, find_packages

setup(
    name="terminal-todo",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
    ],
    entry_points={
        'console_scripts': [
            'todo=terminal_todo.main:main',
        ],
    },
    author="Arjun G Ravi",
    description="A lightweight terminal-based todo application",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
)