# Code Description
This script captures video from a Raspberry Pi camera and records it with timestamps and TTL (Transistor-Transistor Logic) signals. It is designed to run for a specified duration and stores all output files (video, timestamps, and TTL data) in a dated directory. The script is configurable via a JSON file and can handle SIGINT and SIGTERM signals gracefully to ensure data integrity.

# Explanation

1. **Configuration:** The script loads configuration parameters from a JSON file (config.json), making it easy to adjust settings without modifying the code.
    
2. **Signal Handling:** SIGINT and SIGTERM signals are handled gracefully to ensure proper cleanup of resources.

3. **Logging:** Logging is used for debugging and operational tracking.

4. **Threading:** Separate threads are used to handle video output and timestamp writing, improving performance and responsiveness.
    
5. **File Management:** All output files are stored in a directory named with the current date and time, keeping recordings organized.

Copy *VideoAcusitionCode.py* and *killrecording.py* in the same folder (example: /home/user/Desktop in our case) on each Raspberry Pi. 