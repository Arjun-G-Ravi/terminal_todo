from setuptools import setup, find_packages

setup(
    name="terminal-todo",
    version="0.2.0",
    packages=find_packages(),
    entry_points={
        'console_scripts': [
            'todo=terminal_todo.main:main_wrapper',
        ],
    },
    author="Arjun-G-Ravi",
    author_email="your.email@example.com",
    description="A terminal-based todo list application",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.6",
)