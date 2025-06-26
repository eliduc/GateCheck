// static/js/status_updates.js

document.addEventListener("DOMContentLoaded", function() {
    const devicesTable = document.getElementById("devices-table");
    const sensorsTable = document.getElementById("sensors-table");

    const eventSource = new EventSource("/status-stream");

    eventSource.addEventListener("device_status", function(event) {
        const device = JSON.parse(event.data);

        // Check if the device is a sensor or a regular device
        if (device.device_type === 'SENSOR') {
            updateSensorRow(device);
        } else {
            updateDeviceRow(device);
        }
    });

    eventSource.onerror = function(err) {
        console.error("EventSource failed:", err);
        eventSource.close();
    };

    function updateDeviceRow(device) {
        let row = document.getElementById(`device-${device.name}`);
        if (!row) {
            row = devicesTable.insertRow();
            row.id = `device-${device.name}`;
            row.insertCell(0).innerText = device.name;
            row.insertCell(1).innerText = device.address;
            row.insertCell(2).innerText = device.device_type;
            row.insertCell(3);
        }
        const statusCell = row.cells[3];
        statusCell.innerText = device.status_text;
        statusCell.className = device.is_online ? 'online' : 'offline';
    }

    function updateSensorRow(sensor) {
        let row = document.getElementById(`sensor-${sensor.name}`);
        if (!row) {
            row = sensorsTable.insertRow();
            row.id = `sensor-${sensor.name}`;
            row.insertCell(0).innerText = sensor.name;
            row.insertCell(1);
            row.insertCell(2);
            row.insertCell(3);
        }
        const stateCell = row.cells[1];
        stateCell.innerText = sensor.state;
        stateCell.className = sensor.state.toLowerCase() === 'open' ? 'state-open' : 'state-closed';

        const batteryCell = row.cells[2];
        batteryCell.innerText = sensor.battery;

        const statusCell = row.cells[3];
        statusCell.innerText = sensor.status_text;
        statusCell.className = sensor.is_online ? 'online' : 'offline';
    }
});
