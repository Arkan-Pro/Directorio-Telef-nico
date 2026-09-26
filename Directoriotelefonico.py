from __future__ import annotations

import os
import threading
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import urlopen

import customtkinter as ctk
import mysql.connector
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageTk


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

APP_ICON = BASE_DIR / "static" / "image" / "icon G2.ico"
PLACEHOLDER_IMAGE = Image.new("RGB", (360, 260), "#263238")


def database_config() -> dict[str, Any]:
    """Read MySQL connection settings from the project .env file."""
    required = ("DB_HOST", "DB_USER", "DB_PASSWORD")
    missing = [key for key in required if os.getenv(key) is None]
    if missing:
        raise RuntimeError(
            "Faltan variables en .env: " + ", ".join(missing)
        )

    return {
        "host": os.getenv("DB_HOST"),
        "port": int(os.getenv("DB_PORT", "3306")),
        "user": os.getenv("DB_USER"),
        "password": os.getenv("DB_PASSWORD"),
        "database": os.getenv("DB_NAME", "administracion"),
    }


def load_users() -> list[dict[str, Any]]:
    """Load the contact fields used by the directory card."""
    connection = mysql.connector.connect(**database_config())
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT
                CONCAT(nombre, ' ', apellido) AS NombreCompleto,
                telefono,
                email,
                role,
                EnlaceImagen
            FROM usuarios
            """
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        cursor.close()
        connection.close()


def value_as_text(value: Any) -> str:
    if value is None:
        return "No disponible"
    if isinstance(value, bytes):
        return "[imagen almacenada en la base de datos]"
    return str(value)


def image_value(user: dict[str, Any]) -> Any:
    """Find a likely image field (URL, path or BLOB) in the record."""
    preferred = (
        "imagen",
        "imagen_url",
        "enlace_imagen",
        "enlace",
        "foto",
        "fotografia",
        "avatar",
        "image",
        "image_url",
        "url_imagen",
        "url",
        "enlaceimagen",
    )
    normalized = {str(key).lower(): value for key, value in user.items()}
    for name in preferred:
        if name in normalized and normalized[name]:
            return normalized[name]
    for key, value in normalized.items():
        if value and ("image" in key or "imagen" in key or "foto" in key):
            return value
    return None


def load_image(source: Any, size: tuple[int, int]) -> Image.Image:
    if isinstance(source, bytes):
        image = Image.open(BytesIO(source))
    elif source:
        source_text = str(source).strip()
        parsed = urlparse(source_text)
        if parsed.scheme in {"http", "https"}:
            with urlopen(source_text, timeout=8) as response:
                image = Image.open(BytesIO(response.read()))
        else:
            image = Image.open(Path(source_text))
    else:
        image = PLACEHOLDER_IMAGE.copy()
    return image.convert("RGB")


def rounded_image(image: Image.Image, radius: int = 24) -> Image.Image:
    rounded = image.convert("RGBA")
    mask = Image.new("L", rounded.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, rounded.width - 1, rounded.height - 1),
        radius=radius,
        fill=255,
    )
    rounded.putalpha(mask)
    return rounded


class DirectorioTelefonico(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Directorio telefónico")
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        window_width = max(900, int(screen_width * 0.90))
        window_height = max(580, int(screen_height * 0.85))
        position_x = max(0, (screen_width - window_width) // 2)
        position_y = max(0, (screen_height - window_height) // 2)
        self.geometry(
            f"{window_width}x{window_height}+{position_x}+{position_y}"
        )
        self.minsize(900, 580)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        if APP_ICON.exists():
            try:
                self.iconbitmap(str(APP_ICON))
            except Exception:
                try:
                    self.wm_iconbitmap(str(APP_ICON))
                except Exception:
                    pass

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.users: list[dict[str, Any]] = []
        self.image_references: list[ImageTk.PhotoImage] = []
        self.search_text = ctk.StringVar()

        self._build_layout()
        self.search_text.trace_add("write", self.filter_users)
        self.after(100, self.refresh_users)

    def _build_layout(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=28, pady=(24, 12))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header,
            text="Directorio telefónico",
            font=ctk.CTkFont(size=28, weight="bold"),
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            header,
            text="Selecciona un registro para consultar sus datos",
            text_color=("gray35", "gray70"),
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))
        ctk.CTkButton(
            header, text="Actualizar", width=110, command=self.refresh_users
        ).grid(row=0, column=1, rowspan=2, padx=(16, 0))

        list_panel = ctk.CTkFrame(self, corner_radius=12)
        list_panel.grid(row=1, column=0, sticky="nsew", padx=(28, 4), pady=(0, 28))
        list_panel.grid_rowconfigure(2, weight=1)
        list_panel.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            list_panel, text="Contactos", font=ctk.CTkFont(size=18, weight="bold")
        ).grid(row=0, column=0, sticky="w", padx=18, pady=(18, 10))
        ctk.CTkEntry(
            list_panel,
            textvariable=self.search_text,
            placeholder_text="Buscar en los registros...",
        ).grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 12))
        self.contact_list = ctk.CTkScrollableFrame(list_panel, label_text="")
        self.contact_list.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 10))

        self.detail_card = ctk.CTkFrame(self, corner_radius=12)
        self.detail_card.grid(row=1, column=1, sticky="nsew", padx=(4, 28), pady=(0, 28))
        self.detail_card.grid_columnconfigure(0, weight=1)
        self.detail_card.grid_rowconfigure(1, weight=0)
        self.detail_card.grid_rowconfigure(2, weight=0)
        self.detail_title = ctk.CTkLabel(
            self.detail_card,
            text="Detalle del contacto",
            font=ctk.CTkFont(size=20, weight="bold"),
        )
        self.detail_title.grid(row=0, column=0, sticky="w", padx=24, pady=(22, 6))
        self.image_label = ctk.CTkLabel(
            self.detail_card,
            text="",
            width=360,
            height=260,
            corner_radius=0,
            border_width=0,
            fg_color="transparent",
        )
        self.image_label.grid(row=1, column=0, padx=24, pady=(4, 0))
        self.details = ctk.CTkFrame(
            self.detail_card,
            width=360,
            fg_color="transparent",
        )
        self.details.grid(
            row=2,
            column=0,
            sticky="n",
            padx=24,
            pady=(0, 4),
        )
        self.details.grid_propagate(False)
        self.details.grid_columnconfigure(0, weight=1)
        self.show_message("Selecciona un contacto para ver su información.")

    def refresh_users(self) -> None:
        self.show_message("Cargando contactos...")
        threading.Thread(target=self._load_users_worker, daemon=True).start()

    def _load_users_worker(self) -> None:
        try:
            users = load_users()
        except Exception as error:
            message = f"No se pudo cargar la información:\n{error}"
            self.after(0, lambda message=message: self.show_message(message))
            return
        self.after(0, lambda: self._set_users(users))

    def _set_users(self, users: list[dict[str, Any]]) -> None:
        self.users = users
        self.filter_users()
        if users:
            self.show_user(users[0])
        else:
            self.show_message("La tabla usuarios no contiene registros.")

    def filter_users(self, *_args: Any) -> None:
        query = self.search_text.get().strip().lower()
        for child in self.contact_list.winfo_children():
            child.destroy()
        matches = [
            user
            for user in self.users
            if not query
            or query in " ".join(value_as_text(value).lower() for value in user.values())
        ]
        for user in matches:
            self.create_contact_button(user)
        if not matches:
            ctk.CTkLabel(self.contact_list, text="No hay coincidencias.").pack(
                padx=12, pady=20
            )

    def create_contact_button(self, user: dict[str, Any]) -> None:
        title = value_as_text(user.get("NombreCompleto"))
        subtitle = value_as_text(user.get("role"))
        contact = ctk.CTkFrame(
            self.contact_list,
            corner_radius=8,
            cursor="hand2",
            height=58,
        )
        contact.pack(fill="x", padx=4, pady=4)
        contact.pack_propagate(False)
        name_label = ctk.CTkLabel(
            contact,
            text=title,
            anchor="w",
            justify="left",
            font=ctk.CTkFont(size=14, weight="bold"),
        )
        name_label.pack(fill="x", padx=12, pady=(8, 0))
        role_label = ctk.CTkLabel(
            contact,
            text=subtitle,
            anchor="w",
            justify="left",
            text_color=("gray35", "gray70"),
        )
        role_label.pack(fill="x", padx=12, pady=(0, 6))

        for widget in (contact, name_label, role_label):
            widget.bind(
                "<Button-1>",
                lambda _event, selected=user: self.show_user(selected),
            )

    def show_user(self, user: dict[str, Any]) -> None:
        self.detail_title.configure(text="Detalle del contacto")
        for child in self.details.winfo_children():
            child.destroy()
        source = image_value(user)
        try:
            image = load_image(source, (360, 260))
            image.thumbnail((360, 260), Image.Resampling.LANCZOS)
        except Exception:
            image = PLACEHOLDER_IMAGE.copy()
        image = rounded_image(image)
        display_image = ImageTk.PhotoImage(image=image, master=self)
        # Keep every image reference alive while the application is running.
        self.image_references.append(display_image)
        self.image_label.configure(image=display_image, text="")

        visible_fields = (
            ("Nombre Completo", "NombreCompleto"),
            ("Telefono", "telefono"),
            ("Email", "email"),
            ("Role", "role"),
        )
        for label, key in visible_fields:
            value = user.get(key)
            row = ctk.CTkFrame(self.details, fg_color="transparent")
            row.pack(fill="x", pady=2)
            row.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(
                row,
                text=f"{label}:",
                width=130,
                anchor="w",
                font=ctk.CTkFont(weight="bold"),
            ).grid(row=0, column=0, sticky="nw", padx=(0, 10))
            ctk.CTkLabel(
                row,
                text=value_as_text(value),
                anchor="w",
                justify="left",
                wraplength=210,
            ).grid(row=0, column=1, sticky="ew")

    def show_message(self, message: str) -> None:
        self.image_label.configure(text="")
        self.detail_title.configure(text=message)
        for child in self.details.winfo_children():
            child.destroy()


if __name__ == "__main__":
    app = DirectorioTelefonico()
    app.mainloop()
