frappe.ui.form.on('AI Setting', {
    refresh: function(frm) {
        // Clear the container first
        const container = frm.get_field("available_models").$wrapper;
        container.empty();

        // Fetch the curated list of models from the backend
        frappe.call({
            method: "frappe_ai.api.models.get_curated_models",
            callback: function(r) {
                if (r.message && r.message.length > 0) {
                    let models = r.message;
                    
                    // Build the HTML table
                    let html = `
                        <table class="table table-bordered">
                            <thead>
                                <tr>
                                    <th>Model Name</th>
                                    <th>Provider</th>
                                    <th style="width: 15%;">Action</th>
                                </tr>
                            </thead>
                            <tbody>
                    `;
                    
                    models.forEach(model => {
                        html += `
                            <tr>
                                <td>${model.name}</td>
                                <td>${model.provider}</td>
                                <td>
                                    <button class="btn btn-xs btn-primary test-btn" data-model-id="${model.id}">
                                        Test
                                    </button>
                                </td>
                            </tr>
                        `;
                    });

                    html += `</tbody></table>`;
                    container.html(html);

                    // Attach a single event listener to the container
                    container.on('click', '.test-btn', function() {
                        const modelId = $(this).data('model-id');
                        
                        // Set a "testing..." message
                        frm.set_value('response', `Testing model: ${modelId}...\nPlease wait...`);

                        frappe.call({
                            method: "frappe_ai.api.models.run_model_test",
                            args: {
                                model_id: modelId
                            },
                            freeze: true,
                            freeze_message: `Sending prompt to ${modelId}...`,
                            callback: function(r) {
                                if (r.message && r.message.response) {
                                    frm.set_value('response', r.message.response);
                                }
                            },
                            error: function(r) {
                                // Clear the testing message on error
                                frm.set_value('response', `Error: ${r.message}`);
                            }
                        });
                    });
                }
            }
        });
    }
});