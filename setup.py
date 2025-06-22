import sys
import os
from cx_Freeze import setup, Executable

# ADD FILES
files = ['icon.ico', 'themes/']

# TARGET
target = Executable(
    script="main.py",
    base="Win32GUI",
    icon="icon.ico"
)

# SETUP CX FREEZE
setup(
    name="TravelMind",
    version="1.0",
    description="AI Tool for Trip Planning",
    author="Junyan Chen",
    options={'build_exe': {'include_files': files}},
    executables=[target]

)
