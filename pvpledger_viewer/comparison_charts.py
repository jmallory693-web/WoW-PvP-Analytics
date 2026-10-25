"""Separate metric axes and character/type series for advanced comparisons."""
from .charts import RENDER_LOCK, COLORS
from .comparisons import METRICS


def draw(figure, model, metrics):
    metrics = list(dict.fromkeys(metrics))
    if not metrics or any(m not in METRICS for m in metrics):
        raise ValueError('Select known comparison metrics')
    with RENDER_LOCK:
        figure.clear(); figure.set_facecolor('#0c1420')
        for index, metric in enumerate(metrics, 1):
            axis = figure.add_subplot(len(metrics), 1, index); axis.set_facecolor('#0e1928')
            color = 0; any_points = False
            for series in model['series']:
                for kind in series['by_type']:
                    rows = [r for r in series['records'] if (r.get('Type') or 'Unknown') == kind]
                    if metric == 'Win rate':
                        points = series['rolling_by_type'][kind]
                        values = [p['value'] for p in points]
                    else:
                        values = [r.get(metric) for r in rows]
                    n = sum(v is not None for v in values)
                    if n:
                        any_points = True
                        axis.plot(range(1, len(values) + 1), [v if v is not None else float('nan') for v in values],
                                  marker='o', markersize=3, color=COLORS[color % len(COLORS)],
                                  label=f"{series['label']} · {kind} (n={n})")
                    color += 1
            if any_points:
                axis.legend(facecolor='#142131', labelcolor='#e7edf5', fontsize=7, loc='best')
            else:
                reason = f"; rolling win rate needs {model['window']} known results per type" if metric == 'Win rate' else ('\nRoster-only attendance is unknown. Try team ranks or KB/HK.' if 'minute' in metric else '')
                axis.text(.5, .5, 'No data for this comparison' + reason,
                          transform=axis.transAxes, ha='center', color='#a3b2c5', wrap=True)
                axis.set_xticks([]); axis.set_yticks([])
            if metric == 'Win rate':
                axis.set_ylim(0, 100)
            if metric.endswith('rank') and any_points:
                axis.invert_yaxis()
            axis.set_title(metric + ' · ' + model['scope'], color='#e7edf5', fontsize=10)
            axis.set_xlabel('Match / rolling endpoint within each character and match type', color='#a3b2c5', fontsize=8)
            axis.set_ylabel(metric, color='#a3b2c5', fontsize=8)
            axis.tick_params(colors='#a3b2c5', labelsize=8); axis.grid(alpha=.12)
        figure.tight_layout(pad=2)


def export_png(path, model, metrics):
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from .archive import safe_destination
    path = safe_destination(path)
    with RENDER_LOCK:
        figure = Figure(figsize=(13, 4 * len(metrics)), dpi=120); FigureCanvasAgg(figure)
        draw(figure, model, metrics)
        figure.savefig(path, format='png', metadata={'Description': model['note']})
    return str(path)

