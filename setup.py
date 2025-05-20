from setuptools import setup

APP = ["main.py"]
DATA_FILES = [("core", ["core/storyboard.py"])]
OPTIONS = {
    "argv_emulation": True,
    "includes": ["dotenv", "pydub", "openai"],
    "iconfile": None,  # supply .icns here if you have one
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)