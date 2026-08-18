from setuptools import setup, find_packages

setup(
    name="auto-content-scraper",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "requests>=2.31.0",
        "beautifulsoup4>=4.12.0",
        "lxml>=4.9.0",
    ],
    entry_points={
        "console_scripts": [
            "scraper=scraper.main:main",
        ],
    },
    python_requires=">=3.8",
)
