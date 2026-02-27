from flask import Flask, request, render_template_string, Response
import pandas as pd
import io

app = Flask(__name__)

# -------------------------------------------------------------------
# HTML Template (Frontend)
# -------------------------------------------------------------------
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Stoichiometric Calculator</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background-color: #f8f9fa; padding-top: 20px; }
        .card { margin-bottom: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
        .table-custom { background-color: white; }
    </style>
</head>
<body class="container">

    <div class="text-center mb-4">
        <h1 class="text-primary">⚗️ Stoichiometric Calculator</h1>
        <p class="lead">Powered by Python, Flask, and Pandas</p>
    </div>

    <form method="POST" action="/">
        <div class="card p-4">
            <h3>1. Input Parameters</h3>
            <p class="text-muted">Enter your species data below.</p>
            
            <table class="table table-bordered table-custom">
                <thead class="table-light">
                    <tr>
                        <th>Species Name</th>
                        <th>Coefficient (ν)</th>
                        <th>Initial Feed (mol)</th>
                        <th>Molar Mass (g/mol)</th>
                    </tr>
                </thead>
                <tbody>
                    {% for i in range(4) %}
                    <tr>
                        <td><input type="text" class="form-control" name="species" value="{{ vals['species'][i] }}" required></td>
                        <td><input type="number" step="any" class="form-control" name="nu" value="{{ vals['nu'][i] }}" required></td>
                        <td><input type="number" step="any" class="form-control" name="n0" value="{{ vals['n0'][i] }}" required></td>
                        <td><input type="number" step="any" class="form-control" name="mw" value="{{ vals['mw'][i] }}" required></td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>

            <div class="row mt-3">
                <div class="col-md-4">
                    <label class="form-label fw-bold">Limiting Reactant Index (1-4):</label>
                    <input type="number" class="form-control" name="lim_index" min="1" max="4" value="{{ vals['lim_index'] }}" required>
                </div>
                <div class="col-md-4">
                    <label class="form-label fw-bold">Conversion Level (X):</label>
                    <input type="number" step="any" class="form-control" name="conversion" min="0" max="1" value="{{ vals['conversion'] }}" required>
                </div>
                <div class="col-md-4">
                    <label class="form-label fw-bold">Comparison Conversions (comma separated):</label>
                    <input type="text" class="form-control" name="multi_conv" value="{{ vals['multi_conv'] }}" required>
                </div>
            </div>

            <div class="mt-4 text-center">
                <button type="submit" class="btn btn-primary btn-lg px-5">Calculate Flows</button>
            </div>
        </div>
    </form>

    {% if error %}
        <div class="alert alert-danger" role="alert"><strong>Error:</strong> {{ error }}</div>
    {% endif %}

    {% if tables %}
        <div class="card p-4">
            <h3>2. Results Output</h3>
            
            <h5 class="mt-3 text-secondary">📊 Main Stoichiometric Table (at X = {{ vals['conversion'] }})</h5>
            <div class="table-responsive">
                {{ tables['main'] | safe }}
            </div>

            <h5 class="mt-4 text-secondary">📈 Comparison Table (Varying Conversions)</h5>
            <div class="table-responsive">
                {{ tables['comp'] | safe }}
            </div>
            
            <form method="POST" action="/download" class="mt-3">
                {% for i in range(4) %}
                    <input type="hidden" name="species" value="{{ vals['species'][i] }}">
                    <input type="hidden" name="nu" value="{{ vals['nu'][i] }}">
                    <input type="hidden" name="n0" value="{{ vals['n0'][i] }}">
                    <input type="hidden" name="mw" value="{{ vals['mw'][i] }}">
                {% endfor %}
                <input type="hidden" name="lim_index" value="{{ vals['lim_index'] }}">
                <input type="hidden" name="conversion" value="{{ vals['conversion'] }}">
                <input type="hidden" name="multi_conv" value="{{ vals['multi_conv'] }}">
                <button type="submit" class="btn btn-success">📥 Export Main Table to CSV</button>
            </form>
        </div>
    {% endif %}

</body>
</html>
"""

# -------------------------------------------------------------------
# Backend Logic & Stoichiometry Engine
# -------------------------------------------------------------------
def process_stoichiometry(form_data):
    """Core Pandas logic separated from the routing."""
    df = pd.DataFrame({
        "Species": form_data.getlist("species"),
        "Coefficient (ν)": pd.to_numeric(form_data.getlist("nu")),
        "Initial Feed (mol)": pd.to_numeric(form_data.getlist("n0")),
        "Molar Mass (g/mol)": pd.to_numeric(form_data.getlist("mw"))
    })
    
    lim_idx = int(form_data.get("lim_index")) - 1
    conversion = float(form_data.get("conversion"))
    multi_conv = form_data.get("multi_conv")
    
    nu_lim = df.loc[lim_idx, "Coefficient (ν)"]
    n0_lim = df.loc[lim_idx, "Initial Feed (mol)"]
    
    if nu_lim >= 0:
        raise ValueError("The limiting reactant must have a negative coefficient.")

    xi = (n0_lim * conversion) / abs(nu_lim)

    df["Change (mol)"] = df["Coefficient (ν)"] * xi
    df["Final Flow (mol)"] = df["Initial Feed (mol)"] + df["Change (mol)"]
    
    df["Mole Fraction"] = df["Final Flow (mol)"] / df["Final Flow (mol)"].sum()
    df["Final Mass (g)"] = df["Final Flow (mol)"] * df["Molar Mass (g/mol)"]
    df["Mass Fraction"] = df["Final Mass (g)"] / df["Final Mass (g)"].sum()

    conv_list = [float(x.strip()) for x in multi_conv.split(",")]
    comp_df = pd.DataFrame({"Species": df["Species"], "Initial Feed": df["Initial Feed (mol)"]})
    
    for x in conv_list:
        xi_temp = (n0_lim * x) / abs(nu_lim)
        comp_df[f"X = {x}"] = df["Initial Feed (mol)"] + df["Coefficient (ν)"] * xi_temp

    return df, comp_df

# -------------------------------------------------------------------
# Flask Routes
# -------------------------------------------------------------------
@app.route("/", methods=["GET", "POST"])
def index():
    # Setup default values
    current_vals = {
        "species": ["A (Reactant)", "B (Reactant)", "C (Product)", "D (Inert)"],
        "nu": ["-1.0", "-2.0", "1.0", "0.0"],
        "n0": ["100.0", "250.0", "0.0", "50.0"],
        "mw": ["16.0", "32.0", "44.0", "28.0"],
        "lim_index": "1",
        "conversion": "0.5",
        "multi_conv": "0.2, 0.5, 0.8, 0.9"
    }

    if request.method == "POST":
        # Capture current inputs to keep the form populated
        current_vals["species"] = request.form.getlist("species")
        current_vals["nu"] = request.form.getlist("nu")
        current_vals["n0"] = request.form.getlist("n0")
        current_vals["mw"] = request.form.getlist("mw")
        current_vals["lim_index"] = request.form.get("lim_index")
        current_vals["conversion"] = request.form.get("conversion")
        current_vals["multi_conv"] = request.form.get("multi_conv")

        try:
            main_df, comp_df = process_stoichiometry(request.form)
            tables = {
                "main": main_df.to_html(classes="table table-striped table-hover", float_format="%.3f", index=False),
                "comp": comp_df.to_html(classes="table table-striped table-hover", float_format="%.2f", index=False)
            }
            return render_template_string(HTML_TEMPLATE, vals=current_vals, tables=tables)
        except Exception as e:
            return render_template_string(HTML_TEMPLATE, vals=current_vals, error=str(e))

    return render_template_string(HTML_TEMPLATE, vals=current_vals)

@app.route("/download", methods=["POST"])
def download_csv():
    try:
        # Re-calculate cleanly with the hidden fields
        main_df, _ = process_stoichiometry(request.form)
        
        csv_buffer = io.StringIO()
        main_df.to_csv(csv_buffer, index=False)
        
        return Response(
            csv_buffer.getvalue(),
            mimetype="text/csv",
            headers={"Content-disposition": "attachment; filename=stoichiometry_results.csv"}
        )
    except Exception as e:
        return f"Error generating CSV: {str(e)}"

# -------------------------------------------------------------------
# Application Runner
# -------------------------------------------------------------------
if __name__ == "__main__":
    print("\n" + "="*50)
    print("🚀 Starting Flask Server!")
    print("👉 Open your browser and go to: http://127.0.0.1:5000")
    print("="*50 + "\n")
    app.run(debug=True, use_reloader=False)
