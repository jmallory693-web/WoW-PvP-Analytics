"""Figure-local chart styling from a supplied UI palette; no Tk or rcParams."""


def apply_chart_palette(figure, palette):
    if palette is None:
        return  # Classic keeps every original matplotlib setting.
    figure.set_facecolor(palette['BG'])
    for axis in figure.axes:
        axis.set_facecolor(palette['PANEL'])
        axis.title.set_color(palette['TEXT'])
        axis.xaxis.label.set_color(palette['MUTED'])
        axis.yaxis.label.set_color(palette['MUTED'])
        axis.tick_params(colors=palette['MUTED'])
        axis.xaxis.get_offset_text().set_color(palette['MUTED'])
        axis.yaxis.get_offset_text().set_color(palette['MUTED'])
        for spine in axis.spines.values():
            spine.set_color(palette['BORDER'])
        for grid in axis.get_xgridlines() + axis.get_ygridlines():
            grid.set_color(palette['BORDER']); grid.set_alpha(.35)
        for text in axis.texts:
            text.set_color(palette['MUTED'])
        roles = ['ACCENT', 'POSITIVE', 'MUTED', 'NEGATIVE', 'TEXT', 'ACCENT_HOVER']
        metric = axis.get_ylabel().lower()
        if metric.startswith('win rate'):
            roles = ['POSITIVE'] + [role for role in roles if role != 'POSITIVE']
        elif metric.startswith('deaths'):
            roles = ['NEGATIVE', 'MUTED', 'TEXT', 'DISABLED']
        for index, line in enumerate(axis.lines):
            line.set_color(palette[roles[index % len(roles)]])
            if len(axis.lines) > 1:
                line.set_marker(('o', 's', '^', 'D', 'v', 'P', 'X', '*')[index % 8])
        legend = axis.get_legend()
        if legend is not None:
            legend.get_frame().set_facecolor(palette['PANEL'])
            legend.get_frame().set_edgecolor(palette['BORDER'])
            legend.get_title().set_color(palette['TEXT'])
            for text in legend.get_texts():
                text.set_color(palette['TEXT'])
            handles, _ = axis.get_legend_handles_labels()
            for proxy, original in zip(legend.legend_handles, handles):
                proxy.set_color(original.get_color())
                proxy.set_marker(original.get_marker())


def style_annotation(annotation, palette):
    if palette is not None:
        annotation.set_color(palette['TEXT'])
        annotation.get_bbox_patch().set_facecolor(palette['SELECTED'])
        annotation.get_bbox_patch().set_edgecolor(palette['BORDER'])
