"""
Iteration Wallet — setup.py
"""

from setuptools import setup, find_packages
from pathlib import Path

from iteration_wallet.version import WALLET_VERSION, BLACKBOX_VERSION

long_description = (Path(__file__).parent / "README.md").read_text(encoding="utf-8") \
    if (Path(__file__).parent / "README.md").exists() else ""

setup(
    name="iteration-wallet",
    version=WALLET_VERSION,
    description="Local-first, non-destructive project generation custody for AI-assisted work",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Josie Curtsey Cobbley",
    author_email="josie@pubcast.ai",
    url="https://rearviewforesight.com/iteration-wallet",
    license="Proprietary",
    packages=find_packages(
        exclude=[
            "tests", "tests.*",
            "tools", "tools.*",
            "historical_sources", "historical_sources.*",
            "historical_artifacts", "historical_artifacts.*",
            "build", "build.*",
            # The standalone BBX1 distribution is the sole owner of
            # blackbox_plugin. Historical mirrors live outside active package
            # discovery and are never installed by Iteration Wallet.
            "blackbox_plugin", "blackbox_plugin.*",
        ]
    ),
    package_data={
        "iteration_wallet": ["static/*.html", "static/*.css", "static/*.js"],
    },
    python_requires=">=3.10",
    install_requires=[
        "fastapi>=0.111.0",
        "uvicorn[standard]>=0.29.0",
        "pydantic>=2.0.0",
        "requests>=2.31.0",
        "cryptography>=42.0.0",
        f"bbx1-iteration-wallet-plugin=={BLACKBOX_VERSION}",
    ],
    entry_points={
        "console_scripts": [
            "iteration-wallet=iteration_wallet.cli:main",
            "iw=iteration_wallet.cli:main",
            "iw-private-alpha-flow=iteration_wallet.private_alpha_runner:main",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Version Control",
        "Topic :: Security",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
    keywords="vault version-control ai llm project-management security",
)
