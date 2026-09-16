"""Desktop entry point. Double-click the packaged app, or run python app.py."""
if __name__ == "__main__":
    import sys
    if "--self-test" in sys.argv:
        from safe_pdf.selftest import run
        index = sys.argv.index("--self-test")
        output = sys.argv[index + 1] if len(sys.argv) > index + 1 and not sys.argv[index + 1].startswith("--") else None
        run(output, gui="--no-gui" not in sys.argv)
    else:
        from safe_pdf.gui import main
        main()
