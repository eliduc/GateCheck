import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import paramiko
import os
import logging
from datetime import datetime
import stat
import time
import shutil
import socket

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("file_transfer.log"),
        logging.StreamHandler()
    ]
)

class DeviceListDialog(tk.Toplevel):
    def __init__(self, parent, x, y):
        super().__init__(parent)
        self.title("Select Device Type")
        self.result = None
        self.transient(parent)

        main_frame = ttk.Frame(self, padding=5)
        main_frame.pack(fill=tk.BOTH, expand=True)

        self.device_configs = {
            'FR': {'type': 'pi', 'connection': 'pi@fr', 'directory': '/home/pi/GP/'},
            'GP': {'type': 'pi', 'connection': 'pi@gp', 'directory': '/home/pi/CheckGate.'},
            'KODI': {'type': 'pi', 'connection': 'root@libreELEC', 'directory': '/storage/videos/'},
            'Zerow': {'type': 'pi', 'connection': 'pi@192.168.2.68', 'directory': '/home/pi/'},
            'ZerowW128': {'type': 'pi', 'connection': 'pi@ZeroW128', 'directory': '/home/pi/'},
            'Remote PC': {'type': 'pc', 'connection': 'lev@192.168.2.39', 'directory': 'c:/work/Pictures'}
        }

        self.listbox = tk.Listbox(
            main_frame,
            width=15,
            height=len(self.device_configs),
            font=('TkDefaultFont', 10),
            selectmode=tk.SINGLE,
            activestyle='none',
            relief=tk.FLAT,
            bg='white'
        )
        self.listbox.pack(padx=5, pady=5, fill=tk.BOTH, expand=True)

        for device_name in self.device_configs:
            self.listbox.insert(tk.END, device_name)

        button_frame = ttk.Frame(main_frame)
        button_frame.pack(pady=(0, 5), padx=5)

        ttk.Button(button_frame, text="Select", command=self.ok, width=10).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=self.cancel, width=10).pack(side=tk.LEFT, padx=5)

        self.listbox.bind('<Double-Button-1>', lambda e: self.ok())
        self.listbox.bind('<Return>', lambda e: self.ok())
        self.listbox.bind('<Escape>', lambda e: self.cancel())

        self.bind('<Return>', lambda e: self.ok())
        self.bind('<Escape>', lambda e: self.cancel())

        self.geometry(f"+{x}+{y}")
        self.listbox.select_set(0)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.listbox.focus_set()

    def ok(self, event=None):
        if self.listbox.curselection():
            selected = self.listbox.get(self.listbox.curselection())
            self.result = self.device_configs[selected]
            self.result['name'] = selected
        self.destroy()

    def cancel(self, event=None):
        self.result = None
        self.destroy()


class ConnectionDialog(tk.Toplevel):
    def __init__(self, parent, x, y, device_type='pi', default_connection=None, default_directory=None):
        super().__init__(parent)
        self.title("Remote Connection")
        self.result = None
        self.transient(parent)
        self.device_type = device_type

        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="Username@Hostname:").grid(row=0, column=0, padx=5, pady=5, sticky='e')
        self.connection_entry = ttk.Entry(main_frame, width=30)
        self.connection_entry.grid(row=0, column=1, padx=5, pady=5)
        if device_type == 'pi':
            self.connection_entry.insert(0, default_connection or "pi@raspberrypi.local")
        else:
            self.connection_entry.insert(0, "lev@192.168.2.39")

        ttk.Label(main_frame, text="Password:").grid(row=1, column=0, padx=5, pady=5, sticky='e')
        self.password_entry = ttk.Entry(main_frame, show="*", width=30)
        self.password_entry.grid(row=1, column=1, padx=5, pady=5)

        ttk.Label(main_frame, text="Remote Directory:").grid(row=2, column=0, padx=5, pady=5, sticky='e')
        self.directory_entry = ttk.Entry(main_frame, width=30)
        self.directory_entry.grid(row=2, column=1, padx=5, pady=5)
        if device_type == 'pi':
            self.directory_entry.insert(0, default_directory or "/home/pi/")
        else:
            self.directory_entry.insert(0, "C:/work/Pictures/")

        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=3, column=0, columnspan=2, pady=10)

        ttk.Button(button_frame, text="Connect", command=self.ok, width=10).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=self.cancel, width=10).pack(side=tk.LEFT, padx=5)

        self.bind('<Return>', lambda e: self.ok())
        self.bind('<Escape>', lambda e: self.cancel())

        self.connection_entry.bind('<Return>', lambda e: self.ok())
        self.password_entry.bind('<Return>', lambda e: self.ok())
        self.directory_entry.bind('<Return>', lambda e: self.ok())

        self.geometry(f"+{x}+{y}")
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.password_entry.focus_set()

    def ok(self, event=None):
        connection = self.connection_entry.get().strip()
        password = self.password_entry.get()
        directory = self.directory_entry.get().strip()
        if not all([connection, password, directory]):
            messagebox.showerror("Error", "All fields are required!")
            return
        try:
            username, hostname = connection.split('@')
        except ValueError:
            messagebox.showerror("Error", "Invalid format. Please use 'username@hostname' format")
            return
        if not directory.endswith('/'):
            directory += '/'
        self.result = (hostname, username, password, directory)
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
        self.attributes('-topmost', True)

        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        message = f"File '{filename}' already exists.\nWhat would you like to do?"
        ttk.Label(main_frame, text=message).pack(pady=10)

        for text, value in [
            ("Overwrite", "overwrite"),
            ("Skip", "skip"),
            ("Overwrite All", "overwrite_all"),
            ("Skip All", "skip_all"),
            ("Cancel", "cancel")
        ]:
            ttk.Button(
                main_frame,
                text=text,
                command=lambda v=value: self.set_result(v),
                width=20
            ).pack(pady=2)

        self.geometry(f"+{parent.winfo_rootx() + 50}+{parent.winfo_rooty() + 50}")

        self.bind("<Return>", lambda e: self.set_result("overwrite"))

        self.grab_set()
        self.focus_force()
        self.lift()
        self.protocol("WM_DELETE_WINDOW", lambda: self.set_result("cancel"))
        parent.wait_window(self)

    def set_result(self, value):
        self.result = value
        self.grab_release()
        self.destroy()


class ProgressDialog(tk.Toplevel):
    def __init__(self, parent, total_size, total_files=1):
        super().__init__(parent)
        self.title("File Transfer Progress")
        self.transient(parent)

        self.total_size = total_size
        self.total_files = total_files
        self.cancel_flag = False

        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        self.filename_var = tk.StringVar(value="")
        ttk.Label(main_frame, textvariable=self.filename_var).pack(fill=tk.X, pady=5)

        ttk.Label(main_frame, text="File Progress:").pack(fill=tk.X)
        self.file_progress = ttk.Progressbar(main_frame, mode='determinate', maximum=100)
        self.file_progress.pack(fill=tk.X, pady=5)

        self.file_status = tk.StringVar(value="")
        ttk.Label(main_frame, textvariable=self.file_status).pack(fill=tk.X)

        ttk.Label(main_frame, text="\nTotal Progress:").pack(fill=tk.X)
        self.total_progress = ttk.Progressbar(main_frame, mode='determinate', maximum=100)
        self.total_progress.pack(fill=tk.X, pady=5)

        self.total_status = tk.StringVar(value="")
        ttk.Label(main_frame, textvariable=self.total_status).pack(fill=tk.X)

        ttk.Button(main_frame, text="Cancel", command=self.cancel_transfer).pack(pady=10)

        self.geometry("400x250")
        self.geometry(f"+{parent.winfo_rootx() + 50}+{parent.winfo_rooty() + 50}")
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", lambda: None)

        self.bytes_transferred = 0
        self.current_file = 1

    def cancel_transfer(self):
        self.cancel_flag = True
        self.file_status.set("Cancelling...")

    def update_file_progress(self, current_size, total_size, filename=None):
        if filename:
            self.filename_var.set(f"File {self.current_file} of {self.total_files}: {filename}")
        if total_size > 0:
            percentage = min(100, int((current_size * 100) / total_size))
            self.file_progress['value'] = percentage
            self.file_status.set(f"{percentage}% ({self.format_size(current_size)} of {self.format_size(total_size)})")

        total_done = self.bytes_transferred + current_size
        if self.total_size > 0:
            total_percentage = min(100, int((total_done * 100) / self.total_size))
            self.total_progress['value'] = total_percentage
            self.total_status.set(f"Overall: {total_percentage}% completed")

        self.update()

    def file_completed(self, file_size):
        self.bytes_transferred += file_size
        self.current_file += 1
        self.file_progress['value'] = 0
        self.file_status.set("")
        self.update()

    @staticmethod
    def format_size(size):
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} TB"


class CreateDirDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Create Directory")
        self.result = None
        self.transient(parent)

        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="Enter new directory name:").pack(pady=(0,5))
        self.dir_name_var = tk.StringVar()
        entry = ttk.Entry(main_frame, textvariable=self.dir_name_var, width=30)
        entry.pack(pady=5)
        entry.focus_set()

        button_frame = ttk.Frame(main_frame)
        button_frame.pack(pady=5)

        ttk.Button(button_frame, text="OK", command=self.on_ok).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=self.on_cancel).pack(side=tk.LEFT, padx=5)

        self.bind("<Return>", lambda e: self.on_ok())

        self.geometry(f"+{parent.winfo_rootx() + 50}+{parent.winfo_rooty() + 50}")
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.on_cancel)

    def on_ok(self):
        name = self.dir_name_var.get().strip()
        if not name:
            messagebox.showwarning("Warning", "Directory name cannot be empty.")
            return
        self.result = str(name)
        self.destroy()

    def on_cancel(self):
        self.result = None
        self.destroy()


class FileTransfer:
    def __init__(self, master):
        self.master = master
        self.master.title("Universal File Transfer")
        self.master.geometry("1000x600")

        self.ssh = None
        self.sftp = None
        self.remote_directory = None
        self.local_directory = self.normalize_path(os.getcwd())
        self.device_type = None
        self.device_name = None

        self.active_panel = 'local'
        self.sort_order_local = {'name': False, 'extension': False, 'date': False}
        self.sort_order_remote = {'name': False, 'extension': False, 'date': False}
        self.local_selected_item = None
        self.remote_selected_item = None
        self.local_item_id_map = {}
        self.remote_item_id_map = {}

        self.create_widgets()
        self.master.bind('<Tab>', self.switch_active_panel)

        self.selected_files = set()
        self.overwrite_all = False
        self.skip_all = False
        self.file_list = []
        self.remote_file_list = []

    def create_widgets(self):
        self.connection_frame = ttk.Frame(self.master)
        self.connection_frame.pack(padx=10, pady=5, fill=tk.X)

        self.connection_status_label = tk.Label(self.connection_frame, text="Not connected", fg="red")
        self.connection_status_label.pack(side=tk.LEFT, padx=(0, 10))

        self.connect_button = tk.Button(
            self.connection_frame,
            text="Connect to Remote Device",
            width=25,
            command=self.connect_to_remote
        )
        self.connect_button.pack(side=tk.LEFT, padx=5)

        self.device_list_button = tk.Button(
            self.connection_frame,
            text="Device List",
            width=10,
            command=self.show_device_list
        )
        self.device_list_button.pack(side=tk.LEFT)

        self.nav_frame = ttk.Frame(self.master)
        self.nav_frame.pack(fill=tk.X, padx=10, pady=5)

        local_nav_frame = ttk.LabelFrame(self.nav_frame, text="Local Path")
        local_nav_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.local_path_var = tk.StringVar(value=self.local_directory)
        tk.Entry(local_nav_frame, textvariable=self.local_path_var, state='readonly').pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        tk.Button(local_nav_frame, text="Browse", command=self.browse_local_directory).pack(side=tk.LEFT, padx=5)

        remote_nav_frame = ttk.LabelFrame(self.nav_frame, text="Remote Path")
        remote_nav_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.remote_path_var = tk.StringVar(value=self.remote_directory or "Not connected")
        tk.Entry(remote_nav_frame, textvariable=self.remote_path_var, state='readonly').pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        paned = ttk.PanedWindow(self.master, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        columns = ('name', 'extension', 'date', 'size')

        self.local_frame = ttk.Labelframe(paned, text="Local Device")
        paned.add(self.local_frame, weight=1)

        self.local_disk_label = tk.Label(self.local_frame, text="Volume: N/A  Free: N/A", anchor='w')
        self.local_disk_label.pack(side=tk.TOP, fill=tk.X, padx=5, pady=2)

        local_tree_frame = ttk.Frame(self.local_frame)
        local_tree_frame.pack(fill=tk.BOTH, expand=True)
        local_tree_frame.columnconfigure(0, weight=1)
        local_tree_frame.rowconfigure(0, weight=1)

        self.local_tree = ttk.Treeview(
            local_tree_frame,
            columns=columns,
            show='headings',
            selectmode='extended'
        )
        self.local_tree.heading('name', text='Name', command=lambda: self.sort_files('local', 'name'))
        self.local_tree.heading('extension', text='Extension', command=lambda: self.sort_files('local', 'extension'))
        self.local_tree.heading('date', text='Date', command=lambda: self.sort_files('local', 'date'))
        self.local_tree.heading('size', text='Size')
        self.local_tree.column('name', width=200, anchor='w')
        self.local_tree.column('extension', width=70, anchor='w')
        self.local_tree.column('date', width=150, anchor='w')
        self.local_tree.column('size', width=100, anchor='e')
        self.local_tree.grid(row=0, column=0, sticky='nsew')

        local_scrollbar = ttk.Scrollbar(local_tree_frame, orient=tk.VERTICAL, command=self.local_tree.yview)
        local_scrollbar.grid(row=0, column=1, sticky='ns')
        self.local_tree.configure(yscrollcommand=local_scrollbar.set)
        self.local_tree.tag_configure('directory', foreground='blue')
        self.local_tree.tag_configure('file', foreground='black')
        self.local_tree.bind('<Double-1>', lambda e: self.on_double_click('local'))
        self.local_tree.bind('<Return>', lambda e: self.on_double_click('local'))
        self.local_tree.bind('<Delete>', lambda e: self.delete_selected('local'))
        self.local_tree.bind('<Button-1>', lambda e: self.set_active_panel('local'))
        self.local_tree.bind('<<TreeviewSelect>>', self.on_local_selection)

        self.remote_frame = ttk.Labelframe(paned, text="Remote Device")
        paned.add(self.remote_frame, weight=1)

        self.remote_disk_label = tk.Label(self.remote_frame, text="Volume: N/A  Free: N/A", anchor='w')
        self.remote_disk_label.pack(side=tk.TOP, fill=tk.X, padx=5, pady=2)

        remote_tree_frame = ttk.Frame(self.remote_frame)
        remote_tree_frame.pack(fill=tk.BOTH, expand=True)
        remote_tree_frame.columnconfigure(0, weight=1)
        remote_tree_frame.rowconfigure(0, weight=1)

        self.remote_tree = ttk.Treeview(
            remote_tree_frame,
            columns=columns,
            show='headings',
            selectmode='extended'
        )
        self.remote_tree.heading('name', text='Name', command=lambda: self.sort_files('remote', 'name'))
        self.remote_tree.heading('extension', text='Extension', command=lambda: self.sort_files('remote', 'extension'))
        self.remote_tree.heading('date', text='Date', command=lambda: self.sort_files('remote', 'date'))
        self.remote_tree.heading('size', text='Size')
        self.remote_tree.column('name', width=200, anchor='w')
        self.remote_tree.column('extension', width=70, anchor='w')
        self.remote_tree.column('date', width=150, anchor='w')
        self.remote_tree.column('size', width=100, anchor='e')
        self.remote_tree.grid(row=0, column=0, sticky='nsew')

        remote_scrollbar = ttk.Scrollbar(remote_tree_frame, orient=tk.VERTICAL, command=self.remote_tree.yview)
        remote_scrollbar.grid(row=0, column=1, sticky='ns')
        self.remote_tree.configure(yscrollcommand=remote_scrollbar.set)
        self.remote_tree.tag_configure('directory', foreground='blue')
        self.remote_tree.tag_configure('file', foreground='black')
        self.remote_tree.bind('<Double-1>', lambda e: self.on_double_click('remote'))
        self.remote_tree.bind('<Return>', lambda e: self.on_double_click('remote'))
        self.remote_tree.bind('<Delete>', lambda e: self.delete_selected('remote'))
        self.remote_tree.bind('<Button-1>', lambda e: self.set_active_panel('remote'))
        self.remote_tree.bind('<<TreeviewSelect>>', self.on_remote_selection)

        self.button_frame = ttk.Frame(self.master)
        self.button_frame.pack(pady=10)

        ttk.Button(self.button_frame, text="Upload Selected to Remote", command=self.upload_files).pack(side=tk.LEFT, padx=5)
        ttk.Button(self.button_frame, text="Download Selected to Local", command=self.download_files).pack(side=tk.LEFT, padx=5)
        ttk.Button(self.button_frame, text="Create Dir", command=self.create_directory).pack(side=tk.LEFT, padx=5)
        ttk.Button(self.button_frame, text="Delete Selected", command=lambda: self.delete_selected(None)).pack(side=tk.LEFT, padx=5)
        ttk.Button(self.button_frame, text="Refresh Both", command=self.refresh_both).pack(side=tk.LEFT, padx=5)
        ttk.Button(self.button_frame, text="Exit", command=self.master.quit).pack(side=tk.LEFT, padx=5)

        self.load_local_files()
        self.update_disk_info()

    def show_device_list(self):
        try:
            x = self.device_list_button.winfo_rootx()
            y = self.device_list_button.winfo_rooty() + self.device_list_button.winfo_height()
            device_dialog = DeviceListDialog(self.master, x, y)
            self.master.wait_window(device_dialog)
            if device_dialog.result:
                conn_x = self.connect_button.winfo_rootx()
                conn_y = self.connect_button.winfo_rooty() + self.connect_button.winfo_height()
                conn_dialog = ConnectionDialog(
                    self.master,
                    conn_x, conn_y,
                    device_type=device_dialog.result['type'],
                    default_connection=device_dialog.result.get('connection'),
                    default_directory=device_dialog.result.get('directory')
                )
                self.master.wait_window(conn_dialog)
                if conn_dialog.result:
                    connection_string, username, password, dest_dir = conn_dialog.result
                    self.connect_to_remote_with_credentials(
                        connection_string,
                        username,
                        password,
                        dest_dir,
                        device_type=device_dialog.result['type'],
                        device_name=device_dialog.result.get('name')
                    )
        except Exception as e:
            logging.error(f"Error in show_device_list: {str(e)}")
            messagebox.showerror("Error", f"An error occurred: {str(e)}")

    def connect_to_remote_with_credentials(self, hostname, username, password, dest_dir, device_type='pc', device_name=None):
        try:
            logging.info(f"Attempting connection to {hostname}")
            self.remote_directory = self.normalize_path(dest_dir.strip("'\""), is_remote=True)
            if not self.remote_directory.endswith('/'):
                self.remote_directory += '/'
            self.device_type = device_type
            self.device_name = device_name
            self.ssh = paramiko.SSHClient()
            self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            logging.info("Starting SSH connection...")
            self.ssh.connect(
                hostname=hostname,
                username=username,
                password=password,
                look_for_keys=False,
                allow_agent=False,
                timeout=30,
                disabled_algorithms={'pubkeys': ['rsa-sha2-256', 'rsa-sha2-512']}
            )
            logging.info("SSH connection successful")
            logging.info("Opening SFTP session...")
            self.sftp = self.ssh.open_sftp()
            logging.info("SFTP session opened")
            logging.info(f"Testing SFTP by listing {self.remote_directory}")
            try:
                self.sftp.listdir(self.remote_directory)
                logging.info("Directory listing successful")
            except FileNotFoundError:
                messagebox.showerror("Error", f"Remote directory not found: {self.remote_directory}")
                self.disconnect_from_remote()
                return
            except PermissionError:
                messagebox.showerror("Error", f"Access denied to remote directory: {self.remote_directory}")
                self.disconnect_from_remote()
                return
            display_name = device_name or f"{username}@{hostname}"
            logging.info(f"Successfully connected to {display_name}")
            self.connection_status_label.config(text=f"Connected to: {display_name}", fg="green")
            self.remote_path_var.set(self.remote_directory)
            self.connect_button.config(text="Disconnect", command=self.disconnect_from_remote)
            self.load_remote_files()
            self.update_disk_info()
        except paramiko.AuthenticationException:
            logging.error("Authentication failed.")
            messagebox.showerror("Connection Error", "Authentication failed. Please verify username and password.")
            self.disconnect_from_remote()
        except paramiko.SSHException as e:
            logging.error(f"SSH Protocol error: {str(e)}")
            messagebox.showerror("Connection Error", f"SSH error: {str(e)}")
            self.disconnect_from_remote()
        except socket.error as e:
            logging.error(f"Socket error: {str(e)}")
            messagebox.showerror("Connection Error", f"Network error: {str(e)}")
            self.disconnect_from_remote()
        except Exception as e:
            logging.error(f"Connection error: {str(e)}", exc_info=True)
            messagebox.showerror("Connection Error", f"Failed to connect: {str(e)}")
            self.disconnect_from_remote()

    def disconnect_from_remote(self):
        if self.sftp:
            self.sftp.close()
            self.sftp = None
        if self.ssh:
            self.ssh.close()
            self.ssh = None
        device_type = self.device_type or "device"
        logging.info(f"Disconnected from remote {device_type}")
        messagebox.showinfo("Disconnected", f"Disconnected from remote {device_type}.")
        self.connection_status_label.config(text="Not connected", fg="red")
        self.connect_button.config(text="Connect to Remote Device", command=self.connect_to_remote)
        self.device_type = None
        self.device_name = None
        self.remote_directory = None
        self.remote_path_var.set("Not connected")
        self.remote_file_list = []
        self.update_file_tree('remote')

    def connect_to_remote(self):
        if self.ssh and self.sftp:
            messagebox.showinfo("Info", "Already connected to remote device.")
            return
        logging.info("Starting direct connection process...")
        x = self.connect_button.winfo_rootx()
        y = self.connect_button.winfo_rooty() + self.connect_button.winfo_height()
        dialog = ConnectionDialog(self.master, x, y, device_type='pc')
        self.master.wait_window(dialog)
        if not dialog.result:
            return
        hostname, username, password, dest_dir = dialog.result
        self.connect_to_remote_with_credentials(hostname, username, password, dest_dir, device_type='pc')

    def switch_active_panel(self, event=None):
        if self.active_panel == 'local':
            self.set_active_panel('remote')
        else:
            self.set_active_panel('local')
        return 'break'

    def on_local_selection(self, event):
        self.local_selected_item = self.local_tree.selection()
        if self.active_panel != 'local':
            self.local_tree.selection_remove(self.local_selected_item)

    def on_remote_selection(self, event):
        self.remote_selected_item = self.remote_tree.selection()
        if self.active_panel != 'remote':
            self.remote_tree.selection_remove(self.remote_selected_item)

    def set_active_panel(self, panel):
        if panel == self.active_panel:
            return
        if self.active_panel == 'local':
            self.local_selected_item = self.local_tree.selection()
            self.local_tree.selection_remove(self.local_tree.selection())
        else:
            self.remote_selected_item = self.remote_tree.selection()
            self.remote_tree.selection_remove(self.remote_tree.selection())
        self.active_panel = panel
        if panel == 'local':
            if self.local_selected_item:
                self.local_tree.selection_set(self.local_selected_item)
                self.local_tree.focus(self.local_selected_item[0])
            else:
                if '..' in self.local_item_id_map:
                    self.local_selected_item = (self.local_item_id_map['..'],)
                    self.local_tree.selection_set(self.local_selected_item)
                    self.local_tree.focus(self.local_selected_item[0])
            self.local_tree.focus_set()
        else:
            if self.remote_selected_item:
                self.remote_tree.selection_set(self.remote_selected_item)
                self.remote_tree.focus(self.remote_selected_item[0])
            else:
                if '..' in self.remote_item_id_map:
                    self.remote_selected_item = (self.remote_item_id_map['..'],)
                    self.remote_tree.selection_set(self.remote_selected_item)
                    self.remote_tree.focus(self.remote_selected_item[0])
            self.remote_tree.focus_set()

    def format_size(self, size):
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} TB"

    def normalize_path(self, path, is_remote=False):
        normalized = os.path.normpath(str(path)).replace('\\', '/')
        if is_remote and normalized != '/' and not normalized.endswith('/'):
            normalized += '/'
        return normalized

    def browse_local_directory(self):
        new_dir = filedialog.askdirectory(initialdir=self.local_directory)
        if new_dir:
            self.local_directory = self.normalize_path(new_dir)
            self.local_path_var.set(self.local_directory)
            self.load_local_files()

    def get_local_disk_info(self):
        try:
            if os.path.exists(self.local_directory):
                total, used, free = shutil.disk_usage(self.local_directory)
                return {
                    'total': total,
                    'used': used,
                    'free': free,
                    'volume': self.local_directory
                }
        except Exception as e:
            logging.error(f"Error getting local disk info: {str(e)}")
        return None

    def get_remote_disk_info(self):
        try:
            if not self.ssh:
                return None
            current_time = time.time()
            if hasattr(self, '_remote_disk_info_time') and (current_time - self._remote_disk_info_time) < 60:
                return self._remote_disk_info
            cmd = f"df -P '{self.remote_directory}'"
            stdin, stdout, stderr = self.ssh.exec_command(cmd)
            output = stdout.readlines()
            error_output = stderr.read().decode().strip()
            if error_output:
                logging.error(f"Error output from df command: {error_output}")
                return None
            data_line = None
            for line in output[1:]:
                line = line.strip()
                if line:
                    data_line = line
                    break
            if not data_line:
                return None
            data = data_line.split()
            if len(data) >= 6:
                volume = data[0]
                total = int(data[1]) * 1024
                used = int(data[2]) * 1024
                free = int(data[3]) * 1024
                self._remote_disk_info = {
                    'volume': volume,
                    'total': total,
                    'used': used,
                    'free': free
                }
                self._remote_disk_info_time = current_time
                return self._remote_disk_info
            return None
        except Exception as e:
            logging.error(f"Error getting remote disk info: {str(e)}", exc_info=True)
        return None

    def update_disk_info(self):
        try:
            local_info = self.get_local_disk_info()
            if local_info:
                info_text = f"Volume: {local_info['volume']}  Free: {self.format_size(local_info['free'])} of {self.format_size(local_info['total'])}"
                self.local_disk_label.config(text=info_text)
            else:
                self.local_disk_label.config(text="Volume: N/A  Free: N/A")
            remote_info = self.get_remote_disk_info()
            if remote_info:
                info_text = f"Volume: {remote_info['volume']}  Free: {self.format_size(remote_info['free'])} of {self.format_size(remote_info['total'])}"
                self.remote_disk_label.config(text=info_text)
            else:
                self.remote_disk_label.config(text="Volume: N/A  Free: N/A")
        except Exception as e:
            logging.error(f"Error updating disk info: {str(e)}")

    def check_disk_space(self, required_space, is_remote=False):
        try:
            if is_remote:
                disk_info = self.get_remote_disk_info()
            else:
                disk_info = self.get_local_disk_info()
            if not disk_info:
                return False
            return disk_info['free'] >= required_space
        except Exception as e:
            logging.error(f"Error checking disk space: {str(e)}")
            return False

    def load_local_files(self):
        self.local_file_list = []
        attempts = 0
        max_attempts = 5
        while attempts < max_attempts:
            try:
                self.local_directory = self.normalize_path(self.local_directory)
                if not os.path.exists(self.local_directory):
                    raise FileNotFoundError(f"Directory does not exist: {self.local_directory}")
                if os.path.abspath(self.local_directory) != os.path.abspath(os.sep):
                    self.local_file_list.append(('..', '', '', '', ''))
                items = os.listdir(self.local_directory)
                for item in items:
                    try:
                        full_path = os.path.join(self.local_directory, item)
                        stats = os.stat(full_path)
                        date = datetime.fromtimestamp(stats.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                        if os.path.isdir(full_path):
                            self.local_file_list.append((item, '', date, '', 'directory'))
                        else:
                            name, ext = os.path.splitext(item)
                            size = self.format_size(stats.st_size)
                            self.local_file_list.append((name, ext, date, size, 'file'))
                    except (PermissionError, OSError):
                        continue
                self.sort_files('local', 'name')
                self.update_disk_info()
                break
            except FileNotFoundError as e:
                attempts += 1
                if os.path.abspath(self.local_directory) == os.path.abspath(os.sep):
                    messagebox.showerror("Error", "Cannot access parent directories.")
                    break
                self.local_directory = os.path.dirname(self.local_directory)
                self.local_path_var.set(self.local_directory)
            except PermissionError as e:
                messagebox.showerror("Error", f"Access denied to {self.local_directory}")
                self.local_directory = os.path.dirname(self.local_directory)
                self.local_path_var.set(self.local_directory)
                attempts += 1
            except Exception as e:
                messagebox.showerror("Error", f"Failed to load local files: {str(e)}")
                break
        else:
            messagebox.showerror("Error", "Failed to load local files after multiple attempts.")

    def load_remote_files(self):
        if not self.sftp:
            return
        self.remote_file_list = []
        attempts = 0
        max_attempts = 5
        while attempts < max_attempts:
            try:
                self.remote_directory = self.normalize_path(self.remote_directory, is_remote=True)
                if self.remote_directory != '/':
                    self.remote_file_list.append(('..', '', '', '', ''))
                items = self.sftp.listdir_attr(self.remote_directory)
                for item_attr in items:
                    filename = item_attr.filename
                    date = datetime.fromtimestamp(item_attr.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                    if stat.S_ISDIR(item_attr.st_mode):
                        self.remote_file_list.append((filename, '', date, '', 'directory'))
                    else:
                        name, ext = os.path.splitext(filename)
                        size = self.format_size(item_attr.st_size)
                        self.remote_file_list.append((name, ext, date, size, 'file'))
                self.sort_files('remote', 'name')
                self.update_disk_info()
                break
            except FileNotFoundError as e:
                attempts += 1
                if self.remote_directory == '/':
                    messagebox.showerror("Error", "Cannot access parent directories.")
                    break
                self.remote_directory = os.path.dirname(self.remote_directory.rstrip('/'))
                self.remote_path_var.set(self.remote_directory)
            except PermissionError as e:
                messagebox.showerror("Error", f"Access denied to {self.remote_directory}")
                self.remote_directory = os.path.dirname(self.remote_directory.rstrip('/'))
                self.remote_path_var.set(self.remote_directory)
                attempts += 1
            except Exception as e:
                messagebox.showerror("Error", f"Failed to load remote files: {str(e)}")
                break
        else:
            messagebox.showerror("Error", "Failed to load remote files after multiple attempts.")

    def sort_files(self, target, key):
        if target == 'local':
            sort_order = self.sort_order_local
            file_list = self.local_file_list
            tree = self.local_tree
        elif target == 'remote':
            sort_order = self.sort_order_remote
            file_list = self.remote_file_list
            tree = self.remote_tree
        else:
            return
        sort_order[key] = not sort_order[key]
        reverse = sort_order[key]
        parent_dir = next((item for item in file_list if item[0] == '..'), None)
        regular_files = [item for item in file_list if item[0] != '..']
        if key == 'name':
            regular_files.sort(key=lambda x: (x[-1] != 'directory', x[0].lower()), reverse=reverse)
        elif key == 'extension':
            regular_files.sort(key=lambda x: (x[-1] != 'directory', x[1].lower()), reverse=reverse)
        elif key == 'date':
            regular_files.sort(key=lambda x: (x[-1] != 'directory', x[2]), reverse=reverse)
        file_list[:] = ([parent_dir] if parent_dir else []) + regular_files
        self.update_file_tree(target)
        self.update_column_headings(tree, key, reverse)

    def update_column_headings(self, tree, sorted_key, reverse):
        up_arrow = ' ▲'
        down_arrow = ' ▼'
        columns = ['name', 'extension', 'date']
        for col in columns:
            heading_text = col.capitalize()
            if col == sorted_key:
                arrow = down_arrow if reverse else up_arrow
                tree.heading(col, text=heading_text + arrow)
            else:
                tree.heading(col, text=heading_text)

    def update_file_tree(self, target):
        if target == 'local':
            tree = self.local_tree
            file_list = self.local_file_list
        elif target == 'remote':
            tree = self.remote_tree
            file_list = self.remote_file_list
        else:
            return
        tree.delete(*tree.get_children())
        item_id_map = {}
        for item in file_list:
            tags = ('directory',) if item[0] == '..' or item[-1] == 'directory' else ('file',)
            item_id = tree.insert('', 'end', values=item[:-1], tags=tags)
            item_id_map[item[0]] = item_id
        if target == 'local':
            self.local_item_id_map = item_id_map
        else:
            self.remote_item_id_map = item_id_map
        self.update_selection(target)

    def update_selection(self, target):
        if target == 'local':
            tree = self.local_tree
            selected_item = self.local_selected_item
            item_id_map = self.local_item_id_map
        elif target == 'remote':
            tree = self.remote_tree
            selected_item = self.remote_selected_item
            item_id_map = self.remote_item_id_map
        else:
            return
        if not selected_item or not any(item in tree.get_children() for item in selected_item):
            if '..' in item_id_map:
                selected_item = (item_id_map['..'],)
            else:
                children = tree.get_children()
                if children:
                    selected_item = (children[0],)
        if target == 'local':
            self.local_selected_item = selected_item
        else:
            self.remote_selected_item = selected_item
        if self.active_panel == target and selected_item:
            tree.selection_set(selected_item)
            tree.focus(selected_item[0])
            tree.focus_set()
        else:
            tree.selection_remove(tree.selection())

    def on_double_click(self, target):
        try:
            if target == 'local':
                selected = self.local_tree.selection()
                if not selected:
                    return
                item = selected[0]
                values = self.local_tree.item(item)['values']
                if not values:
                    return
                if values[0] == '..':
                    parent = os.path.dirname(self.local_directory)
                    if parent != self.local_directory and os.path.exists(parent):
                        self.local_directory = self.normalize_path(parent)
                        self.local_path_var.set(self.local_directory)
                        self.local_selected_item = None
                        self.load_local_files()
                        self.local_tree.focus_set()
                elif 'directory' in self.local_tree.item(item)['tags']:
                    dir_name = str(values[0])
                    new_path = os.path.join(self.local_directory, dir_name)
                    if os.path.exists(new_path):
                        self.local_directory = self.normalize_path(new_path)
                        self.local_path_var.set(self.local_directory)
                        self.local_selected_item = None
                        self.load_local_files()
                        self.local_tree.focus_set()
                    else:
                        messagebox.showerror("Error", f"Directory not found: {new_path}")
                        self.load_local_files()
            elif target == 'remote' and self.sftp:
                selected = self.remote_tree.selection()
                if not selected:
                    return
                item = selected[0]
                values = self.remote_tree.item(item)['values']
                if not values:
                    return
                if values[0] == '..':
                    parent = os.path.dirname(self.remote_directory.rstrip('/'))
                    if parent != self.remote_directory:
                        self.remote_directory = self.normalize_path(parent, is_remote=True)
                        self.remote_path_var.set(self.remote_directory)
                        self.remote_selected_item = None
                        self.load_remote_files()
                        self.remote_tree.focus_set()
                elif 'directory' in self.remote_tree.item(item)['tags']:
                    dir_name = str(values[0])
                    new_path = os.path.join(self.remote_directory, dir_name).replace('\\', '/')
                    try:
                        self.sftp.listdir(new_path)
                        self.remote_directory = self.normalize_path(new_path, is_remote=True)
                        self.remote_path_var.set(self.remote_directory)
                        self.remote_selected_item = None
                        self.load_remote_files()
                        self.remote_tree.focus_set()
                    except (IOError, FileNotFoundError) as e:
                        messagebox.showerror("Error", f"Cannot access directory: {str(e)}")
                        self.load_remote_files()
        except Exception as e:
            messagebox.showerror("Error", f"Navigation error: {str(e)}")

    def file_exists(self, sftp, path):
        try:
            sftp.stat(path)
            return True
        except FileNotFoundError:
            return False

    def ask_overwrite(self, filename):
        progress_dialog = None
        for widget in self.master.winfo_children():
            if isinstance(widget, ProgressDialog):
                progress_dialog = widget
                progress_dialog.grab_release()
        dialog = OverwriteDialog(self.master, filename)
        result = dialog.result
        if progress_dialog:
            progress_dialog.lift()
            progress_dialog.grab_set()
        return result

    def upload_file(self, local_path, remote_path, progress_dialog, file_size):
        try:
            if not self.check_disk_space(file_size, is_remote=True):
                raise Exception(f"Not enough space on remote device. Required: {self.format_size(file_size)}")
            filename = os.path.basename(local_path)
            def progress_callback(current, total):
                try:
                    if progress_dialog.cancel_flag:
                        return False
                    progress_dialog.update_file_progress(current, total, filename)
                    return True
                except:
                    return True
            self.sftp.put(local_path, remote_path, callback=progress_callback)
            if progress_dialog.cancel_flag:
                try:
                    self.sftp.remove(remote_path)
                except:
                    pass
                return False
            return True
        except Exception as e:
            messagebox.showerror("Error", f"Failed to upload {os.path.basename(local_path)}: {str(e)}")
            return False

    def make_remote_dirs(self, path):
        parts = path.strip('/').split('/')
        current = ''
        for p in parts:
            current = current + '/' + p if current else '/' + p
            try:
                self.sftp.chdir(current)
            except IOError:
                self.sftp.mkdir(current)

    def upload_files(self):
        if not self.sftp:
            messagebox.showwarning("Warning", "Not connected to remote device.")
            return
        selected_items = self.local_tree.selection()
        if not selected_items:
            messagebox.showwarning("Warning", "No items selected!")
            return
        try:
            files_to_transfer = []
            total_size = 0
            for item in selected_items:
                values = self.local_tree.item(item)['values']
                if values[0] == '..':
                    continue
                if 'directory' in self.local_tree.item(item)['tags']:
                    dir_name = str(values[0])
                    local_dir_path = os.path.join(self.local_directory, dir_name)
                    remote_dir_path = os.path.join(self.remote_directory, dir_name).replace('\\', '/')
                    for root, dirs, files in os.walk(local_dir_path):
                        rel_part = os.path.relpath(root, local_dir_path).replace('\\', '/')
                        if rel_part == '.':
                            remote_subdir = remote_dir_path
                        else:
                            remote_subdir = os.path.join(remote_dir_path, rel_part).replace('\\', '/')
                        for f in files:
                            full_local_file = os.path.join(root, f)
                            full_remote_file = os.path.join(remote_subdir, f).replace('\\', '/')
                            size = os.path.getsize(full_local_file)
                            total_size += size
                            files_to_transfer.append((full_local_file, full_remote_file, size))
                else:
                    fn_part_0 = str(values[0])
                    fn_part_1 = str(values[1])
                    filename = fn_part_0 + fn_part_1
                    local_path = os.path.join(self.local_directory, filename).replace('\\', '/')
                    remote_path = os.path.join(self.remote_directory, filename).replace('\\', '/')
                    if os.path.isfile(local_path):
                        size = os.path.getsize(local_path)
                        total_size += size
                        files_to_transfer.append((local_path, remote_path, size))
            if not files_to_transfer:
                return
            progress_dialog = ProgressDialog(self.master, total_size, len(files_to_transfer))
            self.overwrite_all = False
            self.skip_all = False
            for local_path, remote_path, size in files_to_transfer:
                if progress_dialog.cancel_flag:
                    break
                remote_dir = os.path.dirname(remote_path)
                try:
                    self.sftp.chdir(remote_dir)
                except IOError:
                    self.make_remote_dirs(remote_dir)
                file_exists = False
                try:
                    self.sftp.stat(remote_path)
                    file_exists = True
                except FileNotFoundError:
                    file_exists = False
                proceed = False
                if file_exists:
                    if self.overwrite_all:
                        proceed = True
                    elif self.skip_all:
                        progress_dialog.file_completed(size)
                        continue
                    else:
                        filename = os.path.basename(local_path)
                        action = self.ask_overwrite(filename)
                        if action == "cancel":
                            break
                        elif action == "skip":
                            progress_dialog.file_completed(size)
                            continue
                        elif action == "skip_all":
                            self.skip_all = True
                            progress_dialog.file_completed(size)
                            continue
                        elif action == "overwrite_all":
                            self.overwrite_all = True
                            proceed = True
                        elif action == "overwrite":
                            proceed = True
                        else:
                            progress_dialog.file_completed(size)
                            continue
                else:
                    proceed = True
                if proceed:
                    if not self.upload_file(local_path, remote_path, progress_dialog, size):
                        break
                    progress_dialog.file_completed(size)
            progress_dialog.destroy()
        except Exception as e:
            messagebox.showerror("Error", f"Upload operation failed: {str(e)}")
        finally:
            self.overwrite_all = False
            self.skip_all = False
            self.load_remote_files()

    def walk_remote_dir(self, remote_dir):
        dirs = []
        files = []
        try:
            for entry in self.sftp.listdir_attr(remote_dir):
                if stat.S_ISDIR(entry.st_mode):
                    dirs.append(entry.filename)
                else:
                    files.append(entry.filename)
        except Exception as e:
            logging.error(f"Error listing {remote_dir}: {str(e)}")
        yield (remote_dir, dirs, files)
        for d in dirs:
            new_dir = os.path.join(remote_dir, d).replace('\\', '/')
            yield from self.walk_remote_dir(new_dir)

    def download_file(self, remote_path, local_path, progress_dialog, file_size):
        try:
            filename = os.path.basename(remote_path)
            def progress_callback(current, total):
                try:
                    if progress_dialog.cancel_flag:
                        return False
                    progress_dialog.update_file_progress(current, total, filename)
                    return True
                except:
                    return True
            self.sftp.get(remote_path, local_path, callback=progress_callback)
            if progress_dialog.cancel_flag:
                try:
                    os.remove(local_path)
                except:
                    pass
                return False
            return True
        except Exception as e:
            messagebox.showerror("Error", f"Failed to download {os.path.basename(remote_path)}: {str(e)}")
            return False

    def download_files(self):
        if not self.sftp:
            messagebox.showwarning("Warning", "Not connected to remote device.")
            return
        selected_items = self.remote_tree.selection()
        if not selected_items:
            messagebox.showwarning("Warning", "No items selected!")
            return
        try:
            files_to_transfer = []
            total_size = 0
            for item in selected_items:
                values = self.remote_tree.item(item)['values']
                if values[0] == '..':
                    continue
                if 'directory' in self.remote_tree.item(item)['tags']:
                    dir_name = str(values[0])
                    remote_dir_path = os.path.join(self.remote_directory, dir_name).replace('\\', '/')
                    local_dir_path = os.path.join(self.local_directory, dir_name)
                    for root, dirs, files in self.walk_remote_dir(remote_dir_path):
                        rel_part = os.path.relpath(root, remote_dir_path).replace('\\', '/')
                        if rel_part == '.':
                            local_subdir = local_dir_path
                        else:
                            local_subdir = os.path.join(local_dir_path, rel_part)
                        for f in files:
                            full_remote_file = os.path.join(root, f).replace('\\', '/')
                            full_local_file = os.path.join(local_subdir, f)
                            try:
                                st = self.sftp.stat(full_remote_file)
                                total_size += st.st_size
                                files_to_transfer.append((full_remote_file, full_local_file, st.st_size))
                            except Exception as e:
                                logging.error(f"Error getting info for {full_remote_file}: {str(e)}")
                else:
                    fn_part_0 = str(values[0])
                    fn_part_1 = str(values[1])
                    filename = fn_part_0 + fn_part_1
                    remote_path = os.path.join(self.remote_directory, filename).replace('\\', '/')
                    local_path = os.path.join(self.local_directory, filename).replace('\\', '/')
                    try:
                        attrs = self.sftp.stat(remote_path)
                        if stat.S_ISREG(attrs.st_mode):
                            total_size += attrs.st_size
                            files_to_transfer.append((remote_path, local_path, attrs.st_size))
                    except Exception as e:
                        logging.error(f"Error getting info for {filename}: {str(e)}")
            if not files_to_transfer:
                return
            progress_dialog = ProgressDialog(self.master, total_size, len(files_to_transfer))
            self.overwrite_all = False
            self.skip_all = False
            for remote_path, local_path, size in files_to_transfer:
                if progress_dialog.cancel_flag:
                    break
                if os.path.exists(local_path):
                    if self.overwrite_all:
                        proceed = True
                    elif self.skip_all:
                        progress_dialog.file_completed(size)
                        continue
                    else:
                        filename = os.path.basename(local_path)
                        action = self.ask_overwrite(filename)
                        if action == "cancel":
                            break
                        elif action == "skip":
                            progress_dialog.file_completed(size)
                            continue
                        elif action == "skip_all":
                            self.skip_all = True
                            progress_dialog.file_completed(size)
                            continue
                        elif action == "overwrite_all":
                            self.overwrite_all = True
                            proceed = True
                        elif action == "overwrite":
                            proceed = True
                        else:
                            progress_dialog.file_completed(size)
                            continue
                else:
                    proceed = True
                if proceed:
                    os.makedirs(os.path.dirname(local_path), exist_ok=True)
                    if not self.download_file(remote_path, local_path, progress_dialog, size):
                        break
                    progress_dialog.file_completed(size)
            progress_dialog.destroy()
        except Exception as e:
            messagebox.showerror("Error", f"Download operation failed: {str(e)}")
        finally:
            self.overwrite_all = False
            self.skip_all = False
            self.load_local_files()

    def create_directory(self):
        dialog = CreateDirDialog(self.master)
        self.master.wait_window(dialog)
        if dialog.result is None:
            return
        new_dir_name = dialog.result
        if self.active_panel == 'local':
            try:
                target_path = os.path.join(self.local_directory, new_dir_name)
                os.mkdir(target_path)
                self.load_local_files()
                messagebox.showinfo("Directory Created", f"Created local directory: {target_path}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to create local directory: {str(e)}")
        else:
            if not self.sftp:
                messagebox.showwarning("Warning", "Not connected to remote device.")
                return
            try:
                remote_path = os.path.join(self.remote_directory, new_dir_name).replace('\\', '/')
                self.sftp.mkdir(remote_path)
                self.load_remote_files()
                messagebox.showinfo("Directory Created", f"Created remote directory: {remote_path}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to create remote directory: {str(e)}")

    def refresh_both(self):
        self.load_local_files()
        if self.sftp:
            self.load_remote_files()
        self.update_disk_info()

    def on_closing(self):
        if self.sftp:
            self.sftp.close()
        if self.ssh:
            self.ssh.close()
        self.master.destroy()

    def delete_selected(self, source=None):
        if not source:
            source = self.active_panel
        if source == 'local':
            selected_items = self.local_tree.selection()
            if not selected_items:
                return
            if not messagebox.askyesno("Confirm Delete", "Are you sure you want to delete the selected local items?"):
                return
            for item in selected_items:
                values = self.local_tree.item(item)['values']
                if values[0] == '..':
                    continue
                if 'file' in self.local_tree.item(item)['tags']:
                    fn_part_0 = str(values[0])
                    fn_part_1 = str(values[1])
                    filename = fn_part_0 + fn_part_1
                    try:
                        full_path = self.normalize_path(os.path.join(self.local_directory, filename))
                        os.remove(full_path)
                    except Exception as e:
                        messagebox.showerror("Error", f"Failed to delete file {filename}: {str(e)}")
                else:
                    dir_name = str(values[0])
                    full_path = self.normalize_path(os.path.join(self.local_directory, dir_name))
                    if os.listdir(full_path):
                        if not messagebox.askyesno(
                            "Confirm Delete",
                            f"The directory '{dir_name}' is not empty.\nDelete all contents?"
                        ):
                            continue
                    try:
                        shutil.rmtree(full_path)
                    except Exception as e:
                        messagebox.showerror("Error", f"Failed to delete directory {dir_name}: {str(e)}")
            self.load_local_files()
        elif source == 'remote':
            if not self.sftp:
                messagebox.showwarning("Warning", "Not connected to remote device.")
                return
            selected_items = self.remote_tree.selection()
            if not selected_items:
                return
            if not messagebox.askyesno("Confirm Delete", "Are you sure you want to delete the selected remote items?"):
                return
            for item in selected_items:
                values = self.remote_tree.item(item)['values']
                if values[0] == '..':
                    continue
                if 'file' in self.remote_tree.item(item)['tags']:
                    fn_part_0 = str(values[0])
                    fn_part_1 = str(values[1])
                    filename = fn_part_0 + fn_part_1
                    try:
                        full_path = os.path.join(self.remote_directory, filename).replace('\\', '/')
                        self.sftp.remove(full_path)
                    except Exception as e:
                        messagebox.showerror("Error", f"Failed to delete file {filename}: {str(e)}")
                else:
                    dir_name = str(values[0])
                    full_path = os.path.join(self.remote_directory, dir_name).replace('\\', '/')
                    try:
                        dir_items = self.sftp.listdir(full_path)
                        if dir_items:
                            if not messagebox.askyesno(
                                "Confirm Delete",
                                f"The directory '{dir_name}' is not empty.\nDelete all contents (recursively)?"
                            ):
                                continue
                            self.remote_delete_directory(full_path)
                        else:
                            self.sftp.rmdir(full_path)
                    except Exception as e:
                        messagebox.showerror("Error", f"Failed to delete directory {dir_name}: {str(e)}")
            self.load_remote_files()

    def remote_delete_directory(self, path):
        try:
            for item in self.sftp.listdir_attr(path):
                item_path = os.path.join(path, item.filename).replace('\\', '/')
                if stat.S_ISDIR(item.st_mode):
                    self.remote_delete_directory(item_path)
                else:
                    self.sftp.remove(item_path)
            self.sftp.rmdir(path)
        except Exception as e:
            logging.error(f"remote_delete_directory failed: {str(e)}")
            messagebox.showerror("Error", f"Failed to remove {path}: {str(e)}")


if __name__ == "__main__":
    root = tk.Tk()
    app = FileTransfer(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()
