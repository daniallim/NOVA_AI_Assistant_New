import subprocess

import psutil


def gpu_stats():
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=2
        )
        line = result.stdout.strip().splitlines()[0]
        values = [x.strip() for x in line.split(",")]
        return {
            "gpu": float(values[0]),
            "vram_used": float(values[1]),
            "vram_total": float(values[2]),
            "temperature": float(values[3])
        }
    except Exception:
        return {"gpu": 0, "vram_used": 0, "vram_total": 0, "temperature": 0}

def get_stats():
    vm = psutil.virtual_memory()
    cpu_temp = 0
    try:
        temps = psutil.sensors_temperatures()
        if temps:
            first = next(iter(temps.values()))
            if first:
                cpu_temp = first[0].current
    except Exception:
        pass

    return {
        "cpu": psutil.cpu_percent(interval=None),
        "ram": vm.percent,
        "ram_used": vm.used / (1024**3),
        "ram_total": vm.total / (1024**3),
        "disk": psutil.disk_usage("/").percent,
        "gpu_data": gpu_stats(),
        "cpu_temp": cpu_temp
    }
