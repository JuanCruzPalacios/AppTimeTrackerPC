import psutil
import time
from datetime import datetime, timedelta
import json
from pathlib import Path
import os
import tkinter as tk
from tkinter import ttk, simpledialog, messagebox
import threading
from collections import defaultdict
import win32gui
import win32process
import sys
import winreg
import pystray
from PIL import Image

class AppUsageTracker:
    def __init__(self):
        self.usage_data = {}
        self.data_file = Path('app_usage_data.json')
        self.config_file = Path('app_config.json')
        self.tracking = False
        self.active_windows = {}
        self.app_aliases = {}
        self.tracked_apps = set()
        self.removed_apps = set()
        self.highlighted_apps = set()  # Nueva variable para apps destacadas
        self.selected_items = set()
        self.current_date = datetime.now().strftime("%Y-%m-%d")  # Nueva variable para la fecha actual
        self.load_config()
        self.load_existing_data()
        self.create_gui()
        self.setup_autostart()
        
        # Iniciar tracking automáticamente
        self.root.after(1000, self.start_tracking)

    def setup_autostart(self):
        """Configura el inicio automático del programa."""
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        app_name = "AppUsageTracker"
        
        try:
            if getattr(sys, 'frozen', False):
                app_path = f'"{sys.executable}"'
            else:
                app_path = f'"{sys.executable}" "{os.path.abspath(__file__)}"'
            
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, 
                               winreg.KEY_ALL_ACCESS)
            winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, app_path)
            winreg.CloseKey(key)
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo configurar el inicio automático: {str(e)}")

    def create_system_tray(self):
        """Crea el icono del system tray usando pystray."""
        # Crear una imagen para el icono (16x16 pixels, color negro)
        icon_image = Image.new('RGB', (16, 16), 'black')
        
        # Definir el menú del system tray
        def create_menu():
            return pystray.Menu(
                pystray.MenuItem("Mostrar", self.show_window),
                pystray.MenuItem("Tracking", self.toggle_tracking, checked=lambda item: self.tracking),
                pystray.MenuItem("Salir", self.quit_app)
            )

        # Crear el icono del system tray
        self.tray_icon = pystray.Icon(
            "app_tracker",
            icon_image,
            "App Usage Tracker",
            create_menu()
        )

        # Iniciar el icono en un thread separado
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def show_window(self, icon=None):
        """Muestra la ventana principal."""
        self.root.after(0, lambda: (
            self.root.deiconify(),
            self.root.state('normal'),
            self.root.focus_force()
        ))

    def hide_window(self):
        """Oculta la ventana principal."""
        self.root.withdraw()

    def toggle_tracking(self, icon=None):
        """Alterna el estado del tracking."""
        if self.tracking:
            self.stop_tracking()
        else:
            self.start_tracking()
        
        # Actualizar la interfaz
        if self.tracking:
            self.start_button.config(state=tk.DISABLED)
            self.stop_button.config(state=tk.NORMAL)
            self.status_label.config(text="Estado: Rastreando...")
        else:
            self.start_button.config(state=tk.NORMAL)
            self.stop_button.config(state=tk.DISABLED)
            self.status_label.config(text="Estado: Detenido")
        
    def load_config(self):
        """Carga la configuración de aplicaciones."""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                    self.app_aliases = config.get('aliases', {})
                    self.tracked_apps = set(config.get('tracked_apps', []))
                    self.removed_apps = set(config.get('removed_apps', []))
                    self.highlighted_apps = set(config.get('highlighted_apps', []))  # Cargar apps destacadas
            except json.JSONDecodeError:
                self.app_aliases = {}
                self.tracked_apps = set()
                self.removed_apps = set()
                self.highlighted_apps = set()
        else:
            self.app_aliases = {}
            self.tracked_apps = set()
            self.removed_apps = set()
            self.highlighted_apps = set()

    def save_config(self):
        """Guarda la configuración de aplicaciones."""
        config = {
            'aliases': self.app_aliases,
            'tracked_apps': list(self.tracked_apps),
            'removed_apps': list(self.removed_apps),
            'highlighted_apps': list(self.highlighted_apps)  # Guardar apps destacadas
        }
        with open(self.config_file, 'w') as f:
            json.dump(config, f, indent=4)

    def load_existing_data(self):
        if self.data_file.exists():
            try:
                with open(self.data_file, 'r') as f:
                    self.usage_data = json.load(f)
            except json.JSONDecodeError:
                messagebox.showerror("Error", "Error al cargar datos existentes. Iniciando con datos vacíos.")
                self.usage_data = {}

    def save_data(self):
        with open(self.data_file, 'w') as f:
            json.dump(self.usage_data, f, indent=4)

    def get_display_name(self, process_name):
        """Obtiene el nombre personalizado de la aplicación si existe."""
        return self.app_aliases.get(process_name, process_name)

    def rename_app(self):
        """Permite renombrar una aplicación seleccionada."""
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Aviso", "Por favor, selecciona una aplicación para renombrar.")
            return

        item = self.tree.item(selection[0])
        process_name = item['values'][0]
        
        # Obtener el nombre original (sin alias)
        original_name = next((k for k, v in self.app_aliases.items() if v == process_name), process_name)
        
        new_name = simpledialog.askstring(
            "Renombrar Aplicación",
            f"Nuevo nombre para {process_name}:",
            initialvalue=self.get_display_name(original_name)
        )
        
        if new_name:
            self.app_aliases[original_name] = new_name
            self.save_config()
            self.update_tree()

    def filter_apps(self, event, tree, active_processes):
        """Filtra las aplicaciones basado en el texto de búsqueda."""
        search_text = self.search_var.get().lower()
        
        # Limpiar el árbol
        for item in tree.get_children():
            tree.delete(item)
        
        # Filtrar y mostrar las aplicaciones que coinciden
        for proc in sorted(active_processes):
            if proc not in self.tracked_apps and search_text in proc.lower():
                tree.insert("", tk.END, values=(proc,))

    def add_app(self):
        """Añade una aplicación a la lista de rastreo."""
        active_processes = set()
        for proc in psutil.process_iter(['name']):
            try:
                active_processes.add(proc.info['name'])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        # Crear una ventana de selección
        dialog = tk.Toplevel(self.root)
        dialog.title("Agregar Aplicación")
        dialog.geometry("400x500")

        # Frame para el buscador
        search_frame = ttk.Frame(dialog)
        search_frame.pack(fill=tk.X, padx=5, pady=5)

        search_label = ttk.Label(search_frame, text="Buscar:")
        search_label.pack(side=tk.LEFT, padx=5)

        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(search_frame, textvariable=self.search_var)
        search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        label = ttk.Label(dialog, text="Selecciona las aplicaciones a rastrear:")
        label.pack(pady=5)

        # Crear un Treeview para mostrar las aplicaciones
        tree = ttk.Treeview(dialog, columns=("Aplicación",), show="headings")
        tree.heading("Aplicación", text="Aplicación")
        tree.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Agregar scrollbar
        scrollbar = ttk.Scrollbar(dialog, orient=tk.VERTICAL, command=tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        tree.configure(yscrollcommand=scrollbar.set)

        # Llenar el Treeview inicialmente con todas las aplicaciones no rastreadas
        for proc in sorted(active_processes):
            if proc not in self.tracked_apps:
                tree.insert("", tk.END, values=(proc,))

        # Vincular el evento de cambio en el campo de búsqueda
        search_entry.bind('<KeyRelease>', lambda e: self.filter_apps(e, tree, active_processes))

        def add_selected():
            selected = tree.selection()
            for item in selected:
                proc_name = tree.item(item)['values'][0]
                self.tracked_apps.add(proc_name)
            self.save_config()
            dialog.destroy()
            self.update_tree()

        button_frame = ttk.Frame(dialog)
        button_frame.pack(fill=tk.X, pady=5)

        ttk.Button(button_frame, text="Agregar Seleccionadas", command=add_selected).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Cancelar", command=dialog.destroy).pack(side=tk.LEFT, padx=5)

    def remove_app(self):
        """Elimina una aplicación de la lista de rastreo y la agrega a la lista de apps eliminadas."""
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Aviso", "Por favor, selecciona una aplicación para eliminar.")
            return

        item = self.tree.item(selection[0])
        process_name = item['values'][0]
        
        # Obtener el nombre original
        original_name = next((k for k, v in self.app_aliases.items() if v == process_name), process_name)
        
        if messagebox.askyesno("Confirmar", f"¿Estás seguro de querer dejar de rastrear {process_name}?"):
            self.tracked_apps.discard(original_name)
            self.removed_apps.add(original_name)  # Agregar a la lista de apps eliminadas
            if original_name in self.app_aliases:
                del self.app_aliases[original_name]
            self.save_config()
            self.update_tree()
            
    def quit_app(self, icon=None):
        """Cierra completamente la aplicación."""
        if self.tracking:
            self.stop_tracking()
        self.save_data()
        if hasattr(self, 'tray_icon'):
            self.tray_icon.stop()
        self.root.quit()  
            
    def toggle_highlight(self):
        """Alterna el estado destacado de una aplicación."""
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Aviso", "Por favor, selecciona una aplicación para destacar.")
            return

        item = self.tree.item(selection[0])
        process_name = item['values'][0]
        
        # Obtener el nombre original
        original_name = next((k for k, v in self.app_aliases.items() if v == process_name), process_name)
        
        if original_name in self.highlighted_apps:
            self.highlighted_apps.remove(original_name)
        else:
            self.highlighted_apps.add(original_name)
            
        self.save_config()
        self.update_tree()
            
    def create_gui(self):
        self.root = tk.Tk()
        self.root.title("Rastreador de Uso de Aplicaciones")
        self.root.geometry("1000x600")

        # Configurar el system tray
        self.create_system_tray()
        
        # Cambiar el comportamiento al cerrar la ventana
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)

        style = ttk.Style()
        style.theme_use('clam')
        
        # Configurar estilo para items destacados
        style.configure("Highlight.Treeview", background="yellow")

        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Frame para los botones de control
        control_frame = ttk.Frame(main_frame)
        control_frame.pack(fill=tk.X, pady=10)

        # Botones de tracking
        self.start_button = ttk.Button(control_frame, text="Iniciar Seguimiento", command=self.start_tracking)
        self.start_button.pack(side=tk.LEFT, padx=5)

        self.stop_button = ttk.Button(control_frame, text="Detener", command=self.stop_tracking, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=5)

        # Frame para los botones de gestión de aplicaciones
        app_control_frame = ttk.Frame(main_frame)
        app_control_frame.pack(fill=tk.X, pady=5)

        ttk.Button(app_control_frame, text="Agregar Aplicación", command=self.add_app).pack(side=tk.LEFT, padx=5)
        ttk.Button(app_control_frame, text="Eliminar Aplicación", command=self.remove_app).pack(side=tk.LEFT, padx=5)
        ttk.Button(app_control_frame, text="Renombrar Aplicación", command=self.rename_app).pack(side=tk.LEFT, padx=5)
        ttk.Button(app_control_frame, text="Destacar Aplicación", command=self.toggle_highlight).pack(side=tk.LEFT, padx=5)

        # Frame para selección de fecha
        date_frame = ttk.Frame(main_frame)
        date_frame.pack(fill=tk.X, pady=5)

        ttk.Button(date_frame, text="<", command=lambda: self.change_date(-1)).pack(side=tk.LEFT, padx=5)
        self.date_label = ttk.Label(date_frame, text=self.current_date)
        self.date_label.pack(side=tk.LEFT, padx=5)
        ttk.Button(date_frame, text=">", command=lambda: self.change_date(1)).pack(side=tk.LEFT, padx=5)
        ttk.Button(date_frame, text="Hoy", command=self.go_to_today).pack(side=tk.LEFT, padx=5)

        # Tabla de datos
        self.tree = ttk.Treeview(main_frame, columns=("Aplicación", "Tiempo de uso", "Ventanas activas"), show="headings")
        self.tree.heading("Aplicación", text="Aplicación")
        self.tree.heading("Tiempo de uso", text="Tiempo de uso")
        self.tree.heading("Ventanas activas", text="Ventanas activas")
        self.tree.column("Aplicación", width=200)
        self.tree.column("Tiempo de uso", width=150)
        self.tree.column("Ventanas activas", width=500)
        self.tree.pack(fill=tk.BOTH, expand=True, pady=10)

        scrollbar = ttk.Scrollbar(main_frame, orient=tk.VERTICAL, command=self.tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.status_label = ttk.Label(main_frame, text="Estado: Detenido")
        self.status_label.pack(pady=5)

    def format_time(self, seconds):
        """Formato de tiempo que incluye segundos."""
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        return f"{hours}h {minutes}m {secs}s"

    def change_date(self, delta):
        """Cambia la fecha actual por un número de días."""
        current = datetime.strptime(self.current_date, "%Y-%m-%d")
        new_date = current + timedelta(days=delta)
        self.current_date = new_date.strftime("%Y-%m-%d")
        self.date_label.config(text=self.current_date)
        self.update_tree()

    def go_to_today(self):
        """Vuelve a la fecha actual."""
        self.current_date = datetime.now().strftime("%Y-%m-%d")
        self.date_label.config(text=self.current_date)
        self.update_tree()

    def update_tree(self):
        """Actualización del árbol manteniendo las selecciones y mostrando apps destacadas primero."""
        # Guardar las selecciones actuales
        selected = self.tree.selection()
        selected_values = [self.tree.item(item)['values'][0] for item in selected]

        # Limpiar el árbol
        for item in self.tree.get_children():
            self.tree.delete(item)

        if self.current_date in self.usage_data:
            filtered_apps = {
                k: v for k, v in self.usage_data[self.current_date].items()
                if k in self.tracked_apps
            }
            
            # Separar apps destacadas y no destacadas
            highlighted = []
            normal = []
            
            for proc_name, data in filtered_apps.items():
                display_name = self.get_display_name(proc_name)
                current_windows = self.active_windows.get(proc_name, set()) if self.current_date == datetime.now().strftime("%Y-%m-%d") else set()
                windows_str = " | ".join(current_windows) if current_windows else "No hay ventanas activas"
                
                app_data = (proc_name, display_name, data['time'], windows_str)
                if proc_name in self.highlighted_apps:
                    highlighted.append(app_data)
                else:
                    normal.append(app_data)
            
            # Ordenar cada lista por tiempo de uso
            highlighted.sort(key=lambda x: x[2], reverse=True)
            normal.sort(key=lambda x: x[2], reverse=True)
            
            # Insertar primero las apps destacadas
            for proc_name, display_name, time_used, windows_str in highlighted:
                item = self.tree.insert("", tk.END, values=(
                    display_name,
                    self.format_time(time_used),
                    windows_str
                ))
                self.tree.tag_configure('highlighted', background='light yellow')
                self.tree.item(item, tags=('highlighted',))
                
                if display_name in selected_values:
                    self.tree.selection_add(item)
            
            # Luego insertar las apps normales
            for proc_name, display_name, time_used, windows_str in normal:
                item = self.tree.insert("", tk.END, values=(
                    display_name,
                    self.format_time(time_used),
                    windows_str
                ))
                
                if display_name in selected_values:
                    self.tree.selection_add(item)


    def get_process_name(self, hwnd):
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            process = psutil.Process(pid)
            return process.name()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return None

    def get_window_title(self, hwnd):
        return win32gui.GetWindowText(hwnd)

    def is_valid_window(self, hwnd):
        if not win32gui.IsWindowVisible(hwnd):
            return False
        
        title = self.get_window_title(hwnd)
        if not title:
            return False
            
        process_name = self.get_process_name(hwnd)
        if not process_name:
            return False
            
        # Modificar esta condición para incluir todas las ventanas excepto las de apps eliminadas
        if process_name in self.removed_apps:
            return False
            
        rect = win32gui.GetWindowRect(hwnd)
        width = rect[2] - rect[0]
        height = rect[3] - rect[1]
        if width < 100 or height < 100:
            return False
            
        return True

    def enum_windows_callback(self, hwnd, active_apps):
        if self.is_valid_window(hwnd):
            process_name = self.get_process_name(hwnd)
            window_title = self.get_window_title(hwnd)
            if process_name and window_title:
                if process_name not in active_apps:
                    active_apps[process_name] = set()
                active_apps[process_name].add(window_title)

    def get_active_windows(self):
        active_apps = {}
        win32gui.EnumWindows(self.enum_windows_callback, active_apps)
        return active_apps

    def track_usage(self):
        """Versión modificada del tracking que evita el bloqueo de la interfaz."""
        last_update = time.time()
        
        while self.tracking:
            current_time = time.time()
            
            # Actualizar solo si ha pasado 1 segundo
            if current_time - last_update >= 1:
                current_date = datetime.now().strftime("%Y-%m-%d")
                if current_date not in self.usage_data:
                    self.usage_data[current_date] = {}

                # Obtener ventanas activas
                active_windows = self.get_active_windows()
                self.active_windows = active_windows
                
                # Agregar automáticamente las nuevas aplicaciones activas
                for proc_name in active_windows:
                    if proc_name not in self.tracked_apps and proc_name not in self.removed_apps:
                        self.tracked_apps.add(proc_name)
                        self.save_config()
                
                # Actualizar tiempos de uso
                for proc_name in active_windows:
                    if proc_name not in self.usage_data[current_date]:
                        self.usage_data[current_date][proc_name] = {
                            'time': 0,
                            'last_seen': time.time()
                        }
                    else:
                        self.usage_data[current_date][proc_name]['time'] += 1

                self.save_data()
                self.root.after(0, self.update_tree)
                last_update = current_time
            
            # Pequeña pausa para no sobrecargar el CPU
            time.sleep(0.1)
            
            
    def start_tracking(self):
        self.tracking = True
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self.status_label.config(text="Estado: Rastreando...")
        threading.Thread(target=self.track_usage, daemon=True).start()

    def stop_tracking(self):
        self.tracking = False
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        self.status_label.config(text="Estado: Detenido")

    def on_closing(self):
        """Modificado para manejar el cierre de la aplicación."""
        if messagebox.askokcancel("Salir", "¿Realmente deseas cerrar la aplicación?"):
            self.quit_app()
        else:
            self.hide_window()
def main():
    tracker = AppUsageTracker()
    tracker.root.mainloop()

if __name__ == "__main__":
    main()