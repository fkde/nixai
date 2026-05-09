from __future__ import annotations

import typer
import uvicorn
from rich.console import Console

from app.config import config_path, database_path, load_settings
from app.database import init_db
from app.desktop import run_desktop


cli = typer.Typer(help="NixAI local agent runner")
console = Console()


@cli.callback()
def root() -> None:
    """Run NixAI commands."""


@cli.command()
def serve(host: str = "127.0.0.1", port: int = 8765, reload: bool = False) -> None:
    """Start the local NixAI web app."""
    settings = load_settings()
    init_db()
    console.print(f"[bold]NixAI[/bold] serving at http://{host}:{port}")
    console.print(f"Config: {config_path()}")
    console.print(f"Database: {database_path()}")
    console.print(f"Workspace: {settings.workspace_path}")
    uvicorn.run("app.main:app", host=host, port=port, reload=reload)


@cli.command()
def desktop(host: str = "127.0.0.1", port: int = 0) -> None:
    """Start NixAI in a native desktop window."""
    try:
        run_desktop(host=host, port=port)
    except RuntimeError as exc:
        console.print(str(exc), style="red", markup=False)
        raise typer.Exit(code=1) from exc


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
