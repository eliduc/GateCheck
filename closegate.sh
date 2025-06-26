#!/bin/bash
# closegate: Script to activate virtual environment and run CloseGate.py

# Exit immediately if a command exits with a non-zero status
set -e

# Activate the virtual environment
source CheckGate/bin/activate

# Navigate to the CheckGate directory
cd CheckGate

# Run the CloseGate.py script
python CloseGate.py

# Deactivate the virtual environment after script completion
deactivate
