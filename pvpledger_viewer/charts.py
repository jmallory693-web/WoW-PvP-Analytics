"""Matplotlib rendering shared by embedded Tk and standalone PNG export."""
from pathlib import Path
import threading
from .archive import safe_destination
from .trends import METRICS, metric_value
from .metrics import match_date
from .chart_style import apply_chart_palette

RENDER_LOCK = threading.RLock()
COLORS = ('#d8b56c', '#6cd4b0', '#8db8f5', '#f28b94', '#c7a4ec', '#f5b878')


def chart_series(model, metric, teammate=False):
    if metric not in METRICS:
        raise ValueError('Unknown trend metric')
    result = []
    for group in model['teammates' if teammate else 'series']:
        points = group['rolling'] if metric == 'Win rate' else [
            {'key': (r['Character'], r['Realm'], r['Match ID']),
             'date': str(match_date(r) or 'Unknown'),
             'value': metric_value(r, metric), 'count': 1} for r in group['records']]
        label = group['label'] + (' · ' + group['mode'] if teammate else '')
        known = [p['value'] for p in points if p['value'] is not None]
        result.append({'label': label, 'points': points, 'count': len(known),
                       'mean': sum(known) / len(known) if known else None})
    return result


def draw_chart(figure, model, metric, teammate=False, *, palette=None):
    with RENDER_LOCK:
        figure.clear(); figure.set_facecolor('#0c1420')
        axis = figure.add_subplot(111); axis.set_facecolor('#0e1928')
        axis.tick_params(colors='#a3b2c5'); axis.xaxis.label.set_color('#e7edf5'); axis.yaxis.label.set_color('#e7edf5')
        for spine in axis.spines.values():
            spine.set_color('#304460')
        lines = []
        for index, group in enumerate(chart_series(model, metric, teammate)):
            points = group['points']
            # Bound interactive artist size without changing statistics or joining across nulls.
            stride = max(1, (len(points) + 1999) // 2000)
            plotted = points[::stride]
            mean = f"{group['mean']:,.2f}" if group['mean'] is not None else 'Unknown'
            label = f"{group['label']} (n={group['count']}, mean={mean})" if group['count'] else '_nolegend_'
            line, = axis.plot(range(1, len(plotted) + 1),
                              [p['value'] if p['value'] is not None else float('nan') for p in plotted],
                              marker='o', markersize=4, linewidth=1.2, linestyle='-' if stride == 1 else 'None',
                              color=COLORS[index % len(COLORS)], label=label)
            lines.append((line, plotted))
        if any(p['value'] is not None for _, pts in lines for p in pts):
            known_groups = sum(any(p['value'] is not None for p in pts) for _, pts in lines)
            axis.legend(facecolor='#142131', labelcolor='#e7edf5', fontsize=7,
                        ncol=2 if known_groups > 5 else 1, loc='best')
        else:
            axis.text(.5, .5, f'No valid points for {metric}.\nWin rate requires {model["window"]} known results per character/type.'
                      if metric == 'Win rate' else f'No known {metric.lower()} values in this selection.',
                      transform=axis.transAxes, ha='center', va='center', color='#a3b2c5')
        if metric == 'Win rate':
            axis.set_ylim(0, 100)
        if metric.endswith('rank') and axis.has_data():
            axis.invert_yaxis()
        axis.set_title(metric + (' · selected teammate comparisons' if teammate else ' · by character and match type'), color='#e7edf5', fontsize=12)
        axis.set_xlabel('Chronological match/window endpoint within each series (hover for date)\nAt most 2,000 displayed points/series; summary statistics use all records', fontsize=9)
        axis.set_ylabel(metric + (' (%)' if metric == 'Win rate' else ''))
        axis.grid(alpha=.15, color='#a3b2c5')
        apply_chart_palette(figure, palette)
        figure.subplots_adjust(left=.09, right=.98, top=.88, bottom=.3)
        return axis, lines


def export_png(destination, model, metric, teammate=False, *, palette=None):
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    destination = safe_destination(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with RENDER_LOCK:
        figure = Figure(figsize=(13, 7), dpi=120)
        FigureCanvasAgg(figure)
        draw_chart(figure, model, metric, teammate, palette=palette)
        figure.savefig(destination, format='png', facecolor=figure.get_facecolor(),
                       metadata={'Description': model['note']})
    return Path(destination)
