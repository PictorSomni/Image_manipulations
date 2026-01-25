import os
import glob

# Get the directory where this script is located
script_dir = os.path.dirname(os.path.abspath(__file__))

# Find all Python and shell files in the directory
python_files = glob.glob(os.path.join(script_dir, "*.py")) + glob.glob(os.path.join(script_dir, "*.sh"))

# Change permissions to chmod +x (755) for each Python file
for file in python_files:
    os.chmod(file, 0o755)
    print(f"Changed permissions for: {file}")

print(f"\nTotal files modified: {len(python_files)}")
