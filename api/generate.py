import os
import zipfile
from flask import Flask, request, send_file, jsonify

app = Flask(__name__)

def parse_schema(schema):
    # Parse the schema into structured data (mockup logic)
    # Replace this with a proper parser
    trainings = []
    for line in schema.split("\n"):
        if line.strip():
            parts = line.split(":")
            name = parts[0].strip()
            details = parts[1].strip()
            trainings.append({
                "name": name,
                "warmup": {"duration": 600, "power_low": 0.6, "power_high": 0.7},
                "intervals": [
                    {"duration": 300, "power": 0.9, "cadence": 90, "recovery": 300, "recovery_power": 0.6}
                ] * int(details.split()[0]),  # Mock intervals
                "cooldown": {"duration": 600, "power_low": 0.6, "power_high": 0.4}
            })
    return trainings

@app.route('/generate', methods=['POST'])
def generate():
    data = request.json
    schema = data.get('schema', '')
    trainings = parse_schema(schema)
    
    # Create ZWO files
    zip_filename = 'zwo_files.zip'
    with zipfile.ZipFile(zip_filename, 'w') as z:
        for training in trainings:
            zwo_content = f"""
<workout_file>
  <author>Custom Training</author>
  <name>{training['name']}</name>
  <workout>
    <Warmup Duration="{training['warmup']['duration']}" PowerLow="{training['warmup']['power_low']}" PowerHigh="{training['warmup']['power_high']}"/>
"""
            for interval in training['intervals']:
                zwo_content += f"""
    <SteadyState Duration="{interval['duration']}" Power="{interval['power']}" Cadence="{interval['cadence']}"/>
    <SteadyState Duration="{interval['recovery']}" Power="{interval['recovery_power']}" Cadence="85"/>
"""
            zwo_content += f"""
    <Cooldown Duration="{training['cooldown']['duration']}" PowerLow="{training['cooldown']['power_low']}" PowerHigh="{training['cooldown']['power_high']}"/>
  </workout>
</workout_file>
"""
            z.writestr(f"{training['name'].replace(' ', '_')}.zwo", zwo_content)
    
    return send_file(zip_filename, mimetype='application/zip', as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True)
