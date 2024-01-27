"""
This file uses some magic to make running Dandelion
in the background easier
Head to musicbot/__main__.py if you want to see "real" main file
"""


def shutdown(config, p):
    print(config.SHUTDOWN_MESSAGE)
    p.stdin.write("shutdown\n")
    p.stdin.flush()


def main():
    import sys

    if "--run" in sys.argv:
        import runpy

        runpy.run_module("musicbot", run_name="__main__")
        # reminder: there's no `exit` in frozen environment
        sys.exit()

    import signal
    import subprocess

    from config import config

    print("You can close this window and the bot will run in the background")
    print("To stop the bot, press Ctrl+C")

    on_windows = sys.platform == "win32"

    if on_windows:
        import ctypes
        import ctypes.wintypes

        SetHandler = ctypes.windll.kernel32.SetConsoleCtrlHandler

        handler_type = ctypes.WINFUNCTYPE(None, ctypes.wintypes.DWORD)
        SetHandler.argtypes = (handler_type, ctypes.c_bool)

        @handler_type
        def handler(event):
            if event != signal.CTRL_C_EVENT:
                return
            shutdown(config, p)
            SetHandler(handler, False)

        kwargs = {
            "creationflags": subprocess.CREATE_NO_WINDOW
            | subprocess.CREATE_NEW_PROCESS_GROUP
        }
    else:
        kwargs = {"start_new_session": True}

    p = subprocess.Popen(
        # sys.executable may be python interpreter or pyinstaller exe
        [sys.executable, __file__, "--run"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        **kwargs,
    )

    def new_handler(sig, frame):
        """Handle the first interrupt and ignore others
        to prevent showing error instead of subprocess output"""
        nonlocal default_sigint_handler
        h = default_sigint_handler
        if h:
            default_sigint_handler = None
            h(sig, frame)

    default_sigint_handler = signal.signal(signal.SIGINT, new_handler)
    if on_windows and not SetHandler(handler, True):
        print(
            "Failed to set Ctrl+C handler!\n"
            "The bot may not react to this key combination.\n"
            "Please report this bug.",
            file=sys.stderr,
        )
        # can't use windows behaviour
        on_windows = False

    try:
        while line := p.stdout.readline():
            print(line, end="")
    except KeyboardInterrupt:
        if not on_windows:
            shutdown(config, p)
        # display shutdown message
        print(p.stdout.read(), end="")

    exit_code = p.wait()
    if exit_code != 0 and sys.stdin.isatty():
        input("Press Enter to exit... ")
    sys.exit(exit_code)


if __name__ == "__main__":
    from multiprocessing import freeze_support

    freeze_support()
    main()
