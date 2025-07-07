import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import paramiko
import os
import logging
from datetime import datetime
import stat  # Added import for stat module

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("file_transfer.log"),
        logging.StreamHandler()
    ]
)


class ConnectionDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Raspberry Pi Connection Details")
        self.result = None
        self.transient(parent)
        self.grab_set()

        tk.Label(self, text="Username@Hostname:").grid(row=0, column=0, padx=10, pady=5, sticky='e')
        self.connection_entry = tk.Entry(self, width=30)
        self.connection_entry.grid(row=0, column=1, padx=10, pady=5)
        self.connection_entry.insert(0, "pi@gp")  # Default value

        tk.Label(self, text="Password:").grid(row=1, column=0, padx=10, pady=5, sticky='e')
        self.password_entry = tk.Entry(self, show="*", width=30)
        self.password_entry.grid(row=1, column=1, padx=10, pady=5)

        tk.Label(self, text="Remote Directory:").grid(row=2, column=0, padx=10, pady=5, sticky='e')
        self.directory_entry = tk.Entry(self, width=30)
        self.directory_entry.grid(row=2, column=1, padx=10, pady=5)
        self.directory_entry.insert(0, "/home/pi/CheckGate/")  # Default value

        button_frame = tk.Frame(self)
        tk.Button(button_frame, text="Connect", command=self.ok).pack(side=tk.LEFT, padx=5)
        tk.Button(button_frame, text="Cancel", command=self.cancel).pack(side=tk.LEFT, padx=5)
        button_frame.grid(row=3, column=0, columnspan=2, pady=10)

        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.geometry("+%d+%d" % (parent.winfo_rootx()+50, parent.winfo_rooty()+50))
        self.connection_entry.focus_set()
        self.wait_window(self)

    def ok(self, event=None):
        connection = self.connection_entry.get()
        password = self.password_entry.get()
        directory = self.directory_entry.get()
        if '@' not in connection:
            messagebox.showerror("Error", "Invalid connection string. Use format: username@hostname")
            return
        if not all([connection, password, directory]):
            messagebox.showerror("Error", "All fields are required!")
            return
        
        # Ensure directory ends with "/"
        if not directory.endswith('/'):
            directory += '/'
        
        self.result = (connection, password, directory)
        self.destroy()

    def cancel(self, event=None):
        self.result = None
        self.destroy()


class OverwriteDialog(tk.Toplevel):
    def __init__(self, parent, filename):
        super().__init__(parent)
        self.title("File Exists")
        self.result = None
        self.transient(parent)
        self.grab_set()

        tk.Label(self, text=f"{filename} already exists. What would you like to do?").pack(padx=10, pady=10)

        options = ["Overwrite", "Skip", "Overwrite All", "Skip All", "Overwrite Latest", "Cancel"]
        for option in options:
            tk.Button(self, text=option, command=lambda o=option: self.set_result(o)).pack(fill=tk.X, padx=10, pady=2)

        self.protocol("WM_DELETE_WINDOW", lambda: self.set_result("Cancel"))
        self.geometry("+%d+%d" % (parent.winfo_rootx()+50, parent.winfo_rooty()+50))
        self.wait_window(self)

    def set_result(self, value):
        self.result = value.lower().replace(" ", "_")
        self.destroy()


class RaspberryFileTransfer:
    def __init__(self, master):
        self.master = master
        self.master.title("Raspberry Pi File Transfer")
        self.master.geometry("1000x600")

        self.ssh = None
        self.sftp = None
        self.remote_directory = "/home/pi/GP/"

        self.create_widgets()

        self.selected_files = set()
        self.overwrite_all = False
        self.skip_all = False
        self.file_list = []
        self.remote_file_list = []

    def create_widgets(self):
        # Frame for connection
        self.connection_frame = ttk.Frame(self.master)
        self.connection_frame.pack(padx=10, pady=5, fill=tk.X)

        # Connection status label
        self.connection_status_label = tk.Label(self.connection_frame, text="Not connected", fg="red")
        self.connection_status_label.pack(side=tk.LEFT, padx=(0, 10))

        # Connect/Disconnect button
        self.connect_button = tk.Button(
            self.connection_frame,
            text="Connect to Raspberry Pi",
            width=25,
            command=self.connect_to_rpi
        )
        self.connect_button.pack(side=tk.LEFT)

        # Paned window to hold PC and Raspberry PI file lists
        paned = ttk.PanedWindow(self.master, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # PC files frame
        self.local_frame = ttk.Labelframe(paned, text="PC")
        paned.add(self.local_frame, weight=1)

        # Treeview for local files
        self.local_tree = ttk.Treeview(
            self.local_frame,
            columns=('Name', 'Extension', 'Date'),
            show='headings',
            selectmode='extended'
        )
        self.local_tree.heading('Name', text='Name', command=lambda: self.sort_files('local', 'name'))
        self.local_tree.heading('Extension', text='Extension', command=lambda: self.sort_files('local', 'extension'))
        self.local_tree.heading('Date', text='Date', command=lambda: self.sort_files('local', 'date'))
        self.local_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Scrollbar for local files
        local_scrollbar = ttk.Scrollbar(self.local_frame, orient=tk.VERTICAL, command=self.local_tree.yview)
        local_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.local_tree.configure(yscrollcommand=local_scrollbar.set)

        # Raspberry PI files frame
        self.remote_frame = ttk.Labelframe(paned, text="Raspberry PI")
        paned.add(self.remote_frame, weight=1)

        # Treeview for remote files
        self.remote_tree = ttk.Treeview(
            self.remote_frame,
            columns=('Name', 'Extension', 'Date'),
            show='headings',
            selectmode='extended'
        )
        self.remote_tree.heading('Name', text='Name', command=lambda: self.sort_files('remote', 'name'))
        self.remote_tree.heading('Extension', text='Extension', command=lambda: self.sort_files('remote', 'extension'))
        self.remote_tree.heading('Date', text='Date', command=lambda: self.sort_files('remote', 'date'))
        self.remote_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Scrollbar for remote files
        remote_scrollbar = ttk.Scrollbar(self.remote_frame, orient=tk.VERTICAL, command=self.remote_tree.yview)
        remote_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.remote_tree.configure(yscrollcommand=remote_scrollbar.set)

        # Buttons for actions
        self.button_frame = ttk.Frame(self.master)
        self.button_frame.pack(pady=10)

        ttk.Button(self.button_frame, text="Upload Selected to Pi", command=self.upload_files).pack(side=tk.LEFT, padx=5)
        ttk.Button(self.button_frame, text="Download Selected to PC", command=self.download_files).pack(side=tk.LEFT, padx=5)
        ttk.Button(self.button_frame, text="Refresh PC", command=self.load_local_files).pack(side=tk.LEFT, padx=5)
        ttk.Button(self.button_frame, text="Refresh Raspberry PI", command=self.load_remote_files).pack(side=tk.LEFT, padx=5)
        ttk.Button(self.button_frame, text="Exit", command=self.master.quit).pack(side=tk.LEFT, padx=5)

        # Initialize local files
        self.load_local_files()

    def connect_to_rpi(self):
        if self.ssh and self.sftp:
            messagebox.showinfo("Info", "Already connected to Raspberry Pi.")
            return

        dialog = ConnectionDialog(self.master)
        if not dialog.result:
            return  # User cancelled the operation

        connection_string, rpi_password, dest_dir = dialog.result
        try:
            rpi_user, rpi_host = connection_string.split('@')
        except ValueError:
            messagebox.showerror("Error", "Invalid connection string. Use format: username@hostname")
            return

        # Remove quotes if present
        dest_dir = dest_dir.strip("'\"")

        self.remote_directory = dest_dir

        logging.info(f"Remote directory: {self.remote_directory}")

        # Connect to Raspberry Pi
        try:
            self.ssh = paramiko.SSHClient()
            self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.ssh.connect(rpi_host, username=rpi_user, password=rpi_password)
            self.sftp = self.ssh.open_sftp()
            logging.info("Successfully connected to Raspberry Pi")
            messagebox.showinfo("Success", "Connected to Raspberry Pi successfully!")

            # Update connection status label
            self.connection_status_label.config(text=f"Connected to: {connection_string}", fg="green")

            # Change connect button to disconnect
            self.connect_button.config(
                text="Disconnect",
                bg="green",
                fg="white",
                command=self.disconnect_from_rpi
            )

            self.load_remote_files()
        except Exception as e:
            logging.error(f"Failed to connect to Raspberry Pi: {str(e)}")
            messagebox.showerror("Connection Error", f"Failed to connect to Raspberry Pi: {str(e)}")
            self.ssh = None
            self.sftp = None

    def disconnect_from_rpi(self):
        if self.sftp:
            self.sftp.close()
            self.sftp = None
        if self.ssh:
            self.ssh.close()
            self.ssh = None
        logging.info("Disconnected from Raspberry Pi")
        messagebox.showinfo("Disconnected", "Disconnected from Raspberry Pi.")

        # Update connection status label
        self.connection_status_label.config(text="Not connected", fg="red")

        # Change disconnect button back to connect
        self.connect_button.config(
            text="Connect to Raspberry Pi",
            bg=self.master.cget('bg'),  # Reset to default background
            fg="black",
            command=self.connect_to_rpi
        )

        # Clear remote file list
        self.remote_file_list = []
        self.update_file_tree('remote')

    def load_local_files(self):
        self.local_file_list = []
        for file in os.listdir('.'):
            if os.path.isfile(file):
                name, ext = os.path.splitext(file)
                date = datetime.fromtimestamp(os.path.getmtime(file)).strftime('%Y-%m-%d %H:%M:%S')
                self.local_file_list.append((name, ext, date, file))
        self.sort_files('local', 'name')

    def load_remote_files(self):
        if not self.sftp:
            messagebox.showwarning("Warning", "Not connected to Raspberry Pi.")
            return
        self.remote_file_list = []
        try:
            files = self.sftp.listdir_attr(self.remote_directory)
            for file_attr in files:
                if not stat.S_ISDIR(file_attr.st_mode):  # Replaced paramiko.S_ISDIR with stat.S_ISDIR
                    name, ext = os.path.splitext(file_attr.filename)
                    date = datetime.fromtimestamp(file_attr.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                    self.remote_file_list.append((name, ext, date, file_attr.filename))
            self.sort_files('remote', 'name')
        except Exception as e:
            logging.error(f"Failed to list remote files: {str(e)}")
            messagebox.showerror("Error", f"Failed to list remote files: {str(e)}")

    def sort_files(self, target, key):
        if target == 'local':
            if key == 'name':
                self.local_file_list.sort(key=lambda x: x[0].lower())
            elif key == 'extension':
                self.local_file_list.sort(key=lambda x: x[1].lower())
            elif key == 'date':
                self.local_file_list.sort(key=lambda x: x[2], reverse=True)
            self.update_file_tree('local')
        elif target == 'remote':
            if key == 'name':
                self.remote_file_list.sort(key=lambda x: x[0].lower())
            elif key == 'extension':
                self.remote_file_list.sort(key=lambda x: x[1].lower())
            elif key == 'date':
                self.remote_file_list.sort(key=lambda x: x[2], reverse=True)
            self.update_file_tree('remote')

    def update_file_tree(self, target):
        if target == 'local':
            self.local_tree.delete(*self.local_tree.get_children())
            for item in self.local_file_list:
                self.local_tree.insert('', 'end', values=(item[0], item[1], item[2]))
        elif target == 'remote':
            self.remote_tree.delete(*self.remote_tree.get_children())
            for item in self.remote_file_list:
                self.remote_tree.insert('', 'end', values=(item[0], item[1], item[2]))

    def upload_files(self):
        if not self.sftp:
            messagebox.showwarning("Warning", "Not connected to Raspberry Pi.")
            return

        selected_items = self.local_tree.selection()
        if not selected_items:
            messagebox.showwarning("Warning", "No local files selected!")
            return

        # Copy files
        for item in selected_items:
            values = self.local_tree.item(item)['values']
            filename = values[0] + values[1]  # Combine name and extension
            local_path = os.path.join('.', filename)
            remote_path = os.path.join(self.remote_directory, filename)

            try:
                logging.info(f"Attempting to upload {filename} to {remote_path}")
                if self.file_exists(self.sftp, remote_path):
                    if self.overwrite_all:
                        self.upload_file(local_path, remote_path)
                    elif self.skip_all:
                        continue
                    else:
                        action = self.ask_overwrite(filename)
                        if action == "cancel":
                            break
                        elif action == "skip" or action == "skip_all":
                            if action == "skip_all":
                                self.skip_all = True
                            continue
                        elif action == "overwrite" or action == "overwrite_all" or action == "overwrite_latest":
                            if action == "overwrite_all":
                                self.overwrite_all = True
                            if action == "overwrite_latest":
                                local_mtime = os.path.getmtime(local_path)
                                remote_mtime = self.sftp.stat(remote_path).st_mtime
                                if local_mtime <= remote_mtime:
                                    continue
                            self.upload_file(local_path, remote_path)
                else:
                    self.upload_file(local_path, remote_path)
            except Exception as e:
                logging.error(f"Failed to upload {filename}: {str(e)}")
                messagebox.showerror("Error", f"Failed to upload {filename}: {str(e)}")

        self.overwrite_all = False
        self.skip_all = False
        self.load_remote_files()
        messagebox.showinfo("Success", "Upload completed!")

    def download_files(self):
        if not self.sftp:
            messagebox.showwarning("Warning", "Not connected to Raspberry Pi.")
            return

        selected_items = self.remote_tree.selection()
        if not selected_items:
            messagebox.showwarning("Warning", "No remote files selected!")
            return

        # Ask for local destination directory
        dest_dir = filedialog.askdirectory(title="Select Download Destination")
        if not dest_dir:
            return  # User cancelled

        # Copy files
        for item in selected_items:
            values = self.remote_tree.item(item)['values']
            filename = values[0] + values[1]  # Combine name and extension
            remote_path = os.path.join(self.remote_directory, filename)
            local_path = os.path.join(dest_dir, filename)

            try:
                logging.info(f"Attempting to download {remote_path} to {local_path}")
                if os.path.exists(local_path):
                    if self.overwrite_all:
                        self.download_file(remote_path, local_path)
                    elif self.skip_all:
                        continue
                    else:
                        action = self.ask_overwrite(filename)
                        if action == "cancel":
                            break
                        elif action == "skip" or action == "skip_all":
                            if action == "skip_all":
                                self.skip_all = True
                            continue
                        elif action == "overwrite" or action == "overwrite_all" or action == "overwrite_latest":
                            if action == "overwrite_all":
                                self.overwrite_all = True
                            if action == "overwrite_latest":
                                local_mtime = os.path.getmtime(local_path)
                                remote_mtime = self.sftp.stat(remote_path).st_mtime
                                if local_mtime >= remote_mtime:
                                    continue
                            self.download_file(remote_path, local_path)
                else:
                    self.download_file(remote_path, local_path)
            except Exception as e:
                logging.error(f"Failed to download {filename}: {str(e)}")
                messagebox.showerror("Error", f"Failed to download {filename}: {str(e)}")

        self.overwrite_all = False
        self.skip_all = False
        self.load_local_files()
        messagebox.showinfo("Success", "Download completed!")

    def file_exists(self, sftp, path):
        try:
            sftp.stat(path)
            return True
        except FileNotFoundError:
            return False

    def ask_overwrite(self, filename):
        dialog = OverwriteDialog(self.master, filename)
        return dialog.result

    def upload_file(self, local_path, remote_path):
        logging.info(f"Uploading {local_path} to {remote_path}")
        self.sftp.put(local_path, remote_path)
        logging.info(f"Successfully uploaded {local_path} to {remote_path}")

    def download_file(self, remote_path, local_path):
        logging.info(f"Downloading {remote_path} to {local_path}")
        self.sftp.get(remote_path, local_path)
        logging.info(f"Successfully downloaded {remote_path} to {local_path}")

    def on_closing(self):
        if self.sftp:
            self.sftp.close()
        if self.ssh:
            self.ssh.close()
        self.master.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = RaspberryFileTransfer(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()
