import os
from transcoder.config import settings
import time
import subprocess
import re

def convert_with_handbrake(input_file, output_filename, preset):
    
    output_file = settings.OUTPUT_FOLDER + output_filename
    
    command = [
        settings.HANDBRAKE_CLI,
        "-i", input_file,
        "-o", output_file,
        "--preset", preset,
        "--all-audio",
        "-f", settings.OUTPUT_FORMAT,
        "--all-subtitles"
    ]
    
    # Start the conversion
    start_conversion_time = time.time()
    print(f"Conversion Started for {output_filename}")
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    
    # Track progress in real-time
    for line in process.stdout:
        match = re.search(r"Encoding: .*?\s(\d{1,3})\.\d+ %", line)
        if match:
            1 == 1
            #print(f"Conversion Progress: {match.group(1)}%", end="\r", flush=True)

    # Wait for the process to finish
    process.wait()
    end_conversion_time = time.time()
    conversion_time = end_conversion_time - start_conversion_time

    # Check if HandBrakeCLI reported an error (non-zero return code)
    if process.returncode != 0:
        print("HandBrake conversion failed. Skipping this file.")
        # Clean up your temp file if necessary
        if os.path.exists(input_file):
            os.remove(input_file)
            print(f"Deleted temporary file: {input_file}")
        # Optionally log it or handle it however you want
        return None, False
    
    # If we get here, conversion succeeded
    original_size = os.path.getsize(input_file) / (1024 * 1024)  # Convert to MB
    new_size = os.path.getsize(output_file) / (1024 * 1024)    # Convert to MB
    reduction_percentage = ((original_size - new_size) / original_size) * 100 if original_size > 0 else 0
    
    print(f"Size Reduction: {reduction_percentage:.2f}%")
    
    # Remove the temporary file
    os.remove(input_file)
    print(f"Deleted temporary file: {input_file}")
    
    return output_file, new_size >= original_size
 