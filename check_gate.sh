#!/bin/bash
LOGFILE=/home/pi/gate_check.log

# Log the check
echo "$(date): Checking if GateCheck.py is running" >> $LOGFILE

# Check if GateCheck.py is running
if ! /usr/bin/pgrep -f "GateCheck.py" > /dev/null
then
    # Log the restart attempt
    echo "$(date): CheckGate.py not running. Starting it now..." >> $LOGFILE
    # If not running, execute the start command
    /usr/bin/sudo -u pi DISPLAY=:0 /home/pi/CheckGate/start_gate.sh >> $LOGFILE 2>&1
    echo "$(date): start_check.sh executed." >> $LOGFILE
else
    echo "$(date): GateCheck.py is already running." >> $LOGFILE
fi
