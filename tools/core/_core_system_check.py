import subprocess
import json
import re

# --- CONFIGURATION ---
# Setting encoding to 'utf-8' in the run command is the ideal fix, 
# but we must make the script itself robust against the current environment.

def run_shell_command(cmd):
    """Executes a shell command and returns stdout."""
    try:
        # Use subprocess.run to capture output, ensuring we handle potential encoding issues
        # by decoding the result bytes explicitly.
        result = subprocess.run(cmd, shell=True, capture_output=True, text=False, check=True)
        return result.stdout.decode('cp1252', errors='replace') # Use cp1252 as fallback
    except subprocess.CalledProcessError as e:
        return f"ERROR: Command failed with exit code {e.returncode}. Stderr: {e.stderr.decode('cp1252', errors='replace')}"

def parse_systeminfo(output):
    """Parses systeminfo output for OS details and RAM."""
    os_name = "Unknown"
    os_version = "Unknown"
    total_memory = "Unknown"
    
    for line in output.splitlines():
        if "OS Name" in line:
            os_name = line.split(":")[1].strip()
        elif "OS Version" in line:
            os_version = line.split(":")[1].strip()
        elif "Total Physical Memory" in line:
            total_memory = line.split(":")[1].strip()
            
    return {
        "OS_Name": os_name, 
        "OS_Version": os_version, 
        "Total_RAM": total_memory
    }

def parse_tasklist(output):
    """Parses tasklist output to find memory consumers."""
    processes = []
    lines = output.splitlines()
    
    # Skip header lines and process data
    for i, line in enumerate(lines):
        if i > 1: # Start after the header lines
            parts = line.split()
            if len(parts) >= 6:
                process_name = parts[0]
                # Memory usage is often in the 6th or 7th field, depending on spacing
                try:
                    # Attempt to parse the memory usage (e.g., 12,345 K)
                    memory_str = parts[5].replace(',', '')
                    memory_kb = int(memory_str.split()[0]) 
                    processes.append({
                        "process": process_name, 
                        "memory_usage_kb": memory_kb
                    })
                except ValueError:
                    pass # Skip lines where memory parsing fails
    
    # Sort by memory usage descending
    processes.sort(key=lambda x: x['memory_usage_kb'], reverse=True)
    return processes[:5] # Return top 5

def parse_disk_info(output):
    """Parses wmic output for disk space."""
    # Simple regex to capture Size and FreeSpace for the C: drive
    match = re.search(r"Caption=(\'C:\').*Size=(\d+).*Freespace=(\d+)", output)
    
    if match:
        return {
            "Drive": match.group(1),
            "Total_Size_Bytes": int(match.group(2)),
            "Free_Space_Bytes": int(match.group(3))
        }
    else:
        return {"status": "Error: WMIC did not return expected disk data."}

def generate_system_report():
    """Runs multiple diagnostics and compiles a structured report."""
    print("--- Running Core System Diagnostic Suite ---")
    
    # 1. OS & Memory Info
    print("\n[1] Gathering OS and Memory Information...")
    system_info_output = run_shell_command("systeminfo | findstr /B /C:\"OS Name\" /C:\"OS Version\" /C:\"Total Physical Memory\"")
    report_os = parse_systeminfo(system_info_output)

    # 2. Process & RAM Usage
    print("[2] Gathering Process Activity...")
    tasklist_output = run_shell_command("tasklist /v")
    report_processes = parse_tasklist(tasklist_output)

    # 3. Disk Space
    print("[3] Gathering Disk Space Information...")
    disk_info = run_shell_command("wmic logicaldisk where Caption='C:' get Size,Freespace,Caption")
    report_disk = parse_disk_info(disk_info)

    # --- Compiling Final Report ---
    
    # Calculate usage
    try:
        total_ram_bytes = int(report_os['Total_RAM'].replace(' MB', '').replace(',', '')) * 1024 * 1024
        used_memory_bytes = sum(p['memory_usage_kb'] * 1024 for p in report_processes)
        used_percent = (used_memory_bytes / total_ram_bytes) * 100 if total_ram_bytes > 0 else 0
    except Exception:
        used_percent = "N/A (Calculation Error)"
        
    # Format Disk Data for readability (GB)
    disk_size_gb = report_disk.get("Total_Size_Bytes", 0) / (1024**3)
    disk_free_gb = report_disk.get("Free_Space_Bytes", 0) / (1024**3)


    # --- Printing Stylized (ASCII Safe) Report ---
    print("\n" + "="*60)
    print("       GEMMA CORE SYSTEM HEALTH REPORT")
    print("="*60)
    
    # --- SECTION 1: OS & CORE STATUS ---
    print("\n[ SECTION 1: Operating System & Core Status ]")
    print("-" * 40)
    print(f"  OS Name:         {report_os['OS_Name']}")
    print(f"  OS Version:      {report_os['OS_Version']}")
    print(f"  Total RAM:       {report_os['Total_RAM']}")
    
    # --- SECTION 2: MEMORY USAGE ---
    print("\n[ SECTION 2: RAM & Memory Usage ]")
    print("-" * 40)
    print(f"  Calculated RAM Use: {used_percent:.2f}%")
    print(f"  Total Used Memory (Top 5): {sum(p['memory_usage_kb'] for p in report_processes) / 1024:.2f} MB")
    
    # --- SECTION 3: STORAGE ---
    print("\n[ SECTION 3: Storage Capacity (C: Drive) ]")
    print("-" * 40)
    if 'Drive' in report_disk:
        print(f"  Drive:           {report_disk['Drive']}")
        print(f"  Total Capacity:  {disk_size_gb:.2f} GB")
        print(f"  Free Space:      {disk_free_gb:.2f} GB")
    else:
        print(f"  Disk Status:     {report_disk['status']}")

    # --- SECTION 4: TOP PROCESSES ---
    print("\n[ SECTION 4: Top 5 Memory Consumers ]")
    print("-" * 40)
    if report_processes:
        for i, p in enumerate(report_processes):
            mem_mb = p['memory_usage_kb'] / 1024
            print(f"  {i+1}. {p['process']:<20} | Memory: {mem_mb:.2f} MB")
    else:
        print("  No process data available.")
        
    print("\n" + "="*60)

if __name__ == "__main__":
    generate_system_report()