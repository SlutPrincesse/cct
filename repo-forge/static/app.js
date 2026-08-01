async function deleteRepo(repoName) {
    if (!confirm(`Delete repository ${repoName}?`)) return;
    const res = await fetch(`/api/repos/${repoName}`, { method: 'DELETE' });
    if (res.ok) location.reload();
}

async function toggleUnit(unitId, selected) {
    const formData = new FormData();
    formData.append('unit_id', unitId);
    formData.append('selected', selected);
    await fetch('/api/select', { method: 'POST', body: formData });
}

async function clearSelections() {
    if (!confirm('Clear all selections?')) return;
    const formData = new FormData();
    formData.append('repo_name', '');
    await fetch('/api/select/clear', { method: 'POST', body: formData });
    location.reload();
}

document.getElementById('cloneForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const form = e.target;
    const status = document.getElementById('cloneStatus');
    status.innerHTML = '<span class="spinner"></span> Cloning repository...';
    status.className = 'status-message show status-info';

    const formData = new FormData();
    formData.append('repo_url', form.repo_url.value);
    formData.append('branch', form.branch.value);

    const res = await fetch('/api/clone', { method: 'POST', body: formData });
    const data = await res.json();

    if (data.success) {
        status.innerHTML = 'Repository cloned successfully!';
        status.className = 'status-message show status-success';
        setTimeout(() => location.reload(), 1000);
    } else {
        status.innerHTML = data.message || 'Clone failed';
        status.className = 'status-message show status-error';
    }
});

document.getElementById('generateForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const form = e.target;
    const status = document.getElementById('generateStatus');
    status.innerHTML = '<span class="spinner"></span> Generating app...';
    status.className = 'status-message show status-info';

    const formData = new FormData();
    formData.append('project_name', form.project_name.value);
    formData.append('description', form.description.value);

    const res = await fetch('/api/generate', { method: 'POST', body: formData });
    const data = await res.json();

    if (data.success) {
        status.innerHTML = `App generated! ID: ${data.project_id}`;
        status.className = 'status-message show status-success';
        setTimeout(() => window.location.href = '/compile', 1500);
    } else {
        status.innerHTML = data.message || 'Generation failed';
        status.className = 'status-message show status-error';
    }
});
