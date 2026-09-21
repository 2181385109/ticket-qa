' Keep the WSL distro (and the Docker containers inside it) alive without an open terminal.
' Put a copy into  shell:startup  so it runs at logon. Killing this wsl.exe stops the distro a few seconds later.
Set sh = CreateObject("WScript.Shell")
sh.Run "wsl.exe -d Ubuntu-24.04 -u root -- sleep infinity", 0, False
