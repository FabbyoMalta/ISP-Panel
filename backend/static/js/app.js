// Progressive enhancement: normal links and forms remain fully functional without JS.
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.sidebar nav a').forEach(link => {
    if (link.pathname === location.pathname) link.setAttribute('aria-current', 'page');
  });
  const dataNode = document.getElementById('metric-history');
  const canvas = document.getElementById('metric-chart');
  if (dataNode && canvas && window.Chart) {
    const data = JSON.parse(dataNode.textContent);
    new Chart(canvas, { type: 'line', data: {
      labels: data.map(row => row.date),
      datasets: [{ label: data[0]?.unit || 'Valor', data: data.map(row => row.value), borderColor: '#188f82', backgroundColor: '#e3f4ef', fill: true, tension: 0.25 }]
    }, options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true } } } });
  }
});
