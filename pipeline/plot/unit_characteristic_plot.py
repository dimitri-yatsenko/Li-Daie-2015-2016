import numpy as np
import matplotlib as mpl
import matplotlib.pyplot as plt
import seaborn as sns
import itertools
import pandas as pd

from pipeline import experiment, ephys, psth
from pipeline.plot import (_plot_with_sem, _extract_one_stim_dur, _get_units_hemisphere,
                           _plot_stacked_psth_diff, _plot_avg_psth, _get_photostim_time_and_duration,
                           jointplot_w_hue)

m_scale = 1200
_plt_xmin = -3
_plt_xmax = 2


def plot_clustering_quality(probe_insertion):
    probe_insertion = probe_insertion.proj()
    amp, snr, spk_rate, isi_violation = (ephys.Unit * ephys.UnitStat
                                         * ephys.ProbeInsertion.InsertionLocation & probe_insertion).fetch(
        'unit_amp', 'unit_snr', 'avg_firing_rate', 'isi_violation')

    metrics = {'amp': amp,
               'snr': snr,
               'isi': np.array(isi_violation) * 100,  # to percentage
               'rate': np.array(spk_rate)}
    label_mapper = {'amp': 'Amplitude',
                    'snr': 'Signal to noise ratio (SNR)',
                    'isi': 'ISI violation (%)',
                    'rate': 'Firing rate (spike/s)'}

    fig, axs = plt.subplots(2, 3, figsize=(12, 8))
    fig.subplots_adjust(wspace=0.4)

    for (m1, m2), ax in zip(itertools.combinations(list(metrics.keys()), 2), axs.flatten()):
        ax.plot(metrics[m1], metrics[m2], '.k')
        ax.set_xlabel(label_mapper[m1])
        ax.set_ylabel(label_mapper[m2])

        # cosmetic
        ax.spines['right'].set_visible(False)
        ax.spines['top'].set_visible(False)


def plot_unit_characteristic(probe_insertion, axs=None):
    probe_insertion = probe_insertion.proj()
    amp, snr, spk_rate, x, y, insertion_depth = (
            ephys.Unit * ephys.ProbeInsertion.InsertionLocation * ephys.UnitStat
            & probe_insertion & 'unit_quality != "all"').fetch(
        'unit_amp', 'unit_snr', 'avg_firing_rate', 'unit_posx', 'unit_posy', 'dv_location')

    insertion_depth = np.where(np.isnan(insertion_depth), 0, insertion_depth)

    metrics = pd.DataFrame(list(zip(*(amp/amp.max(), snr/snr.max(), spk_rate/spk_rate.max(), x, y + insertion_depth))))
    metrics.columns = ['amp', 'snr', 'rate', 'x', 'y']

    if axs is None:
        fig, axs = plt.subplots(1, 3, figsize=(10, 8))
        fig.subplots_adjust(wspace=0.6)

    assert axs.size == 3

    cosmetic = {'legend': None,
                'linewidth': 1.75,
                'alpha': 0.9,
                'facecolor': 'none', 'edgecolor': 'k'}

    sns.scatterplot(data=metrics, x='x', y='y', s=metrics.amp*m_scale, ax=axs[0], **cosmetic)
    sns.scatterplot(data=metrics, x='x', y='y', s=metrics.snr*m_scale, ax=axs[1], **cosmetic)
    sns.scatterplot(data=metrics, x='x', y='y', s=metrics.rate*m_scale, ax=axs[2], **cosmetic)

    # cosmetic
    for title, ax in zip(('Amplitude', 'SNR', 'Firing rate'), axs.flatten()):
        ax.spines['right'].set_visible(False)
        ax.spines['top'].set_visible(False)
        ax.set_title(title)
        ax.set_xlim((-10, 60))


def plot_unit_selectivity(probe_insertion, axs=None):
    probe_insertion = probe_insertion.proj()
    attr_names = ['unit', 'period', 'period_selectivity', 'contra_firing_rate',
                       'ipsi_firing_rate', 'unit_posx', 'unit_posy', 'dv_location']
    selective_units = (psth.PeriodSelectivity * ephys.Unit * ephys.ProbeInsertion.InsertionLocation
                       * experiment.Period & probe_insertion & 'period_selectivity != "non-selective"').fetch(*attr_names)
    selective_units = pd.DataFrame(selective_units).T
    selective_units.columns = attr_names
    selective_units.period_selectivity.astype('category')

    # --- account for insertion depth (manipulator depth)
    selective_units.unit_posy = (selective_units.unit_posy
                                 + np.where(np.isnan(selective_units.dv_location.values.astype(float)),
                                            0, selective_units.dv_location.values.astype(float)))

    # --- get ipsi vs. contra firing rate difference
    f_rate_diff = np.abs(selective_units.ipsi_firing_rate - selective_units.contra_firing_rate)
    selective_units['f_rate_diff'] = f_rate_diff / f_rate_diff.max()

    # --- prepare for plotting
    cosmetic = {'legend': None,
                'linewidth': 0.0001}
    ymax = selective_units.unit_posy.max() + 100

    # a bit of hack to get 'open circle'
    pts = np.linspace(0, np.pi * 2, 24)
    circ = np.c_[np.sin(pts) / 2, -np.cos(pts) / 2]
    vert = np.r_[circ, circ[::-1] * .7]

    open_circle = mpl.path.Path(vert)

    # --- plot
    if axs is None:
        fig, axs = plt.subplots(1, 3, figsize=(10, 8))
        fig.subplots_adjust(wspace=0.6)

    assert axs.size == 3

    for (title, df), ax in zip(((p, selective_units[selective_units.period == p])
                                for p in ('sample', 'delay', 'response')), axs):
        sns.scatterplot(data=df, x='unit_posx', y='unit_posy',
                        s=df.f_rate_diff.values.astype(float)*m_scale,
                        hue='period_selectivity', marker=open_circle,
                        palette={'contra-selective': 'b', 'ipsi-selective': 'r'},
                        ax=ax, **cosmetic)
        contra_p = (df.period_selectivity == 'contra-selective').sum() / len(df) * 100
        # cosmetic
        ax.spines['right'].set_visible(False)
        ax.spines['top'].set_visible(False)
        ax.set_title(f'{title}\n% contra: {contra_p:.2f}\n% ipsi: {100-contra_p:.2f}')
        ax.set_xlim((-10, 60))
        # ax.set_ylim((0, ymax))


def plot_unit_bilateral_photostim_effect(probe_insertion, axs=None):
    probe_insertion = probe_insertion.proj()
    cue_onset = (experiment.Period & 'period = "delay"').fetch1('period_start')

    no_stim_cond = (psth.TrialCondition
                    & {'trial_condition_name':
                       'all_noearlylick_both_alm_nostim'}).fetch1('KEY')

    bi_stim_cond = (psth.TrialCondition
                    & {'trial_condition_name':
                       'all_noearlylick_both_alm_stim'}).fetch1('KEY')

    # get photostim duration
    stim_durs = np.unique((experiment.Photostim & experiment.PhotostimEvent
                           * psth.TrialCondition().get_trials('all_noearlylick_both_alm_stim')
                           & probe_insertion).fetch('duration'))
    stim_dur = _extract_one_stim_dur(stim_durs)

    units = ephys.Unit & probe_insertion & 'unit_quality != "all"'

    metrics = pd.DataFrame(columns=['unit', 'x', 'y', 'frate_change'])

    # XXX: could be done with 1x fetch+join
    for u_idx, unit in enumerate(units.fetch('KEY')):

        x, y = (ephys.Unit & unit).fetch1('unit_posx', 'unit_posy')

        nostim_psth, nostim_edge = (
            psth.UnitPsth & {**unit, **no_stim_cond}).fetch1('unit_psth')

        bistim_psth, bistim_edge = (
            psth.UnitPsth & {**unit, **bi_stim_cond}).fetch1('unit_psth')

        # compute the firing rate difference between contra vs. ipsi within the stimulation duration
        ctrl_frate = nostim_psth[np.logical_and(nostim_edge[1:] >= cue_onset, nostim_edge[1:] <= cue_onset + stim_dur)]
        stim_frate = bistim_psth[np.logical_and(bistim_edge[1:] >= cue_onset, bistim_edge[1:] <= cue_onset + stim_dur)]

        frate_change = np.abs(stim_frate.mean() - ctrl_frate.mean()) / ctrl_frate.mean()

        metrics.loc[u_idx] = (int(unit['unit']), x, y, frate_change)

    metrics.frate_change = metrics.frate_change / metrics.frate_change.max()

    if axs is None:
        fig, axs = plt.subplots(1, 1, figsize=(4, 8))

    cosmetic = {'legend': None,
                'linewidth': 1.75,
                'alpha': 0.9,
                'facecolor': 'none', 'edgecolor': 'k'}

    sns.scatterplot(data=metrics, x='x', y='y', s=metrics.frate_change*m_scale,
                    ax=axs, **cosmetic)

    axs.spines['right'].set_visible(False)
    axs.spines['top'].set_visible(False)
    axs.set_title('% change')
    axs.set_xlim((-10, 60))


def plot_stacked_contra_ipsi_psth(units, axs=None):
    units = units.proj()

    if axs is None:
        fig, axs = plt.subplots(1, 2, figsize=(20, 20))
    assert axs.size == 2

    period_starts = (experiment.Period
                     & 'period in ("sample", "delay", "response")').fetch(
                         'period_start')

    hemi = _get_units_hemisphere(units)

    conds_i = (psth.TrialCondition
               & {'trial_condition_name':
                  'good_noearlylick_left_hit' if hemi == 'left' else 'good_noearlylick_right_hit'}).fetch1('KEY')

    conds_c = (psth.TrialCondition
               & {'trial_condition_name':
                  'good_noearlylick_right_hit' if hemi == 'left' else 'good_noearlylick_left_hit'}).fetch1('KEY')

    sel_i = (ephys.Unit * psth.UnitSelectivity
             & 'unit_selectivity = "ipsi-selective"' & units)

    sel_c = (ephys.Unit * psth.UnitSelectivity
             & 'unit_selectivity = "contra-selective"' & units)

    # ipsi selective ipsi trials
    psth_is_it = (psth.UnitPsth * sel_i.proj('unit_posy') & conds_i).fetch(order_by='unit_posy desc')
    # ipsi selective contra trials
    psth_is_ct = (psth.UnitPsth * sel_i.proj('unit_posy') & conds_c).fetch(order_by='unit_posy desc')
    # contra selective contra trials
    psth_cs_ct = (psth.UnitPsth * sel_c.proj('unit_posy') & conds_c).fetch(order_by='unit_posy desc')
    # contra selective ipsi trials
    psth_cs_it = (psth.UnitPsth * sel_c.proj('unit_posy') & conds_i).fetch(order_by='unit_posy desc')

    _plot_stacked_psth_diff(psth_cs_ct, psth_cs_it, ax=axs[0],
                            vlines=period_starts, flip=True)

    axs[0].set_title('Contra-selective Units')
    axs[0].set_ylabel('Unit')
    axs[0].set_xlabel('Time to go-cue (s)')
    axs[0].set_xlim([_plt_xmin, _plt_xmax])

    _plot_stacked_psth_diff(psth_is_it, psth_is_ct, ax=axs[1],
                            vlines=period_starts)

    axs[1].set_title('Ipsi-selective Units')
    axs[1].set_ylabel('Unit')
    axs[1].set_xlabel('Time to go-cue (s)')
    axs[1].set_xlim([_plt_xmin, _plt_xmax])


def plot_selectivity_sorted_stacked_contra_ipsi_psth(units, axs=None):
    units = units.proj()

    if axs is None:
        fig, axs = plt.subplots(1, 2, figsize=(20, 20))
    assert axs.size == 2

    period_starts = (experiment.Period
                     & 'period in ("sample", "delay", "response")').fetch(
                         'period_start')

    hemi = _get_units_hemisphere(units)

    conds_i = (psth.TrialCondition
               & {'trial_condition_name':
                  'good_noearlylick_left_hit' if hemi == 'left' else 'good_noearlylick_right_hit'}).fetch1('KEY')

    conds_c = (psth.TrialCondition
               & {'trial_condition_name':
                  'good_noearlylick_right_hit' if hemi == 'left' else 'good_noearlylick_left_hit'}).fetch1('KEY')

    # separate units to: i) sample/delay not response; ii) sample/delay or response; iii) not sample/delay and response
    sample_delay_units = units & (psth.PeriodSelectivity
                                  & 'period in ("sample", "delay")'
                                  & 'period_selectivity != "non-selective"')
    sample_delay_units = sample_delay_units & (psth.PeriodSelectivity
                                               & 'period = "response"'
                                               & 'period_selectivity = "non-selective"')
    sample_delay_response_units = units & (psth.PeriodSelectivity
                                           & 'period in ("sample", "delay")'
                                           & 'period_selectivity != "non-selective"')
    sample_delay_response_units = sample_delay_response_units & (psth.PeriodSelectivity
                                                                 & 'period = "response"'
                                                                 & 'period_selectivity != "non-selective"')
    response_units = units & (psth.PeriodSelectivity
                              & 'period in ("sample", "delay")'
                              & 'period_selectivity = "non-selective"')
    response_units = response_units & (psth.PeriodSelectivity
                                       & 'period = "response"'
                                       & 'period_selectivity != "non-selective"')

    ipsi_selective_psth, contra_selective_psth = [], []
    for units in (sample_delay_units, sample_delay_response_units, response_units):
        sel_i = (ephys.Unit * psth.UnitSelectivity
                 & 'unit_selectivity = "ipsi-selective"' & units)
        sel_c = (ephys.Unit * psth.UnitSelectivity
                 & 'unit_selectivity = "contra-selective"' & units)

        # ipsi selective ipsi trials
        psth_is_it = (psth.UnitPsth * sel_i.proj('unit_posy') & conds_i).fetch(order_by='unit_posy desc')
        # ipsi selective contra trials
        psth_is_ct = (psth.UnitPsth * sel_i.proj('unit_posy') & conds_c).fetch(order_by='unit_posy desc')
        # contra selective contra trials
        psth_cs_ct = (psth.UnitPsth * sel_c.proj('unit_posy') & conds_c).fetch(order_by='unit_posy desc')
        # contra selective ipsi trials
        psth_cs_it = (psth.UnitPsth * sel_c.proj('unit_posy') & conds_i).fetch(order_by='unit_posy desc')

        contra_selective_psth.append(_plot_stacked_psth_diff(psth_cs_ct, psth_cs_it, ax=axs[0], flip=True, plot=False))
        ipsi_selective_psth.append(_plot_stacked_psth_diff(psth_is_it, psth_is_ct, ax=axs[1], plot=False))

    contra_selective_psth = np.vstack(contra_selective_psth)
    ipsi_selective_psth = np.vstack(ipsi_selective_psth)

    xlim = -3, 2
    im = axs[0].imshow(contra_selective_psth, cmap=plt.cm.bwr,
                       aspect=4.5/contra_selective_psth.shape[0],
                       extent=[-3, 3, 0, contra_selective_psth.shape[0]])
    im.set_clim((-1, 1))

    im = axs[1].imshow(ipsi_selective_psth, cmap=plt.cm.bwr,
                       aspect=4.5/ipsi_selective_psth.shape[0],
                       extent=[-3, 3, 0, ipsi_selective_psth.shape[0]])
    im.set_clim((-1, 1))

    # cosmetic
    for ax, title in zip(axs, ('Contra-selective Units', 'Ipsi-selective Units')):
        for x in period_starts:
            ax.axvline(x=x, linestyle='--', color='k')
        ax.set_title(title)
        ax.set_ylabel('Unit')
        ax.set_xlabel('Time to go-cue (s)')
        ax.set_xlim(xlim)


def plot_avg_contra_ipsi_psth(units, axs=None):
    units = units.proj()

    if axs is None:
        fig, axs = plt.subplots(1, 2, figsize=(16, 6))
    assert axs.size == 2

    period_starts = (experiment.Period
                     & 'period in ("sample", "delay", "response")').fetch(
                         'period_start')

    hemi = _get_units_hemisphere(units)

    good_unit = ephys.Unit & 'unit_quality != "all"'

    conds_i = (psth.TrialCondition
               & {'trial_condition_name':
                  'good_noearlylick_left_hit' if hemi == 'left' else 'good_noearlylick_right_hit'}).fetch('KEY')

    conds_c = (psth.TrialCondition
               & {'trial_condition_name':
                  'good_noearlylick_right_hit' if hemi == 'left' else 'good_noearlylick_left_hit'}).fetch('KEY')

    sel_i = (ephys.Unit * psth.UnitSelectivity
             & 'unit_selectivity = "ipsi-selective"' & units)

    sel_c = (ephys.Unit * psth.UnitSelectivity
             & 'unit_selectivity = "contra-selective"' & units)

    psth_is_it = (((psth.UnitPsth & conds_i)
                   * ephys.Unit.proj('unit_posy'))
                  & good_unit.proj() & sel_i.proj()).fetch(
                      'unit_psth', order_by='unit_posy desc')

    psth_is_ct = (((psth.UnitPsth & conds_c)
                   * ephys.Unit.proj('unit_posy'))
                  & good_unit.proj() & sel_i.proj()).fetch(
                      'unit_psth', order_by='unit_posy desc')

    psth_cs_ct = (((psth.UnitPsth & conds_c)
                   * ephys.Unit.proj('unit_posy'))
                  & good_unit.proj() & sel_c.proj()).fetch(
                      'unit_psth', order_by='unit_posy desc')

    psth_cs_it = (((psth.UnitPsth & conds_i)
                   * ephys.Unit.proj('unit_posy'))
                  & good_unit.proj() & sel_c.proj()).fetch(
                      'unit_psth', order_by='unit_posy desc')

    _plot_avg_psth(psth_cs_it, psth_cs_ct, period_starts, axs[0],
                   'Contra-selective')
    _plot_avg_psth(psth_is_it, psth_is_ct, period_starts, axs[1],
                   'Ipsi-selective')

    ymax = max([ax.get_ylim()[1] for ax in axs])
    for ax in axs:
        ax.set_ylim((0, ymax))
        ax.set_xlim([_plt_xmin, _plt_xmax])


def plot_psth_photostim_effect(units, condition_name_kw=['both_alm'], axs=None):
    """
    For the specified `units`, plot PSTH comparison between stim vs. no-stim with left/right trial instruction
    The stim location (or other appropriate search keywords) can be specified in `condition_name_kw` (default: bilateral ALM)
    """
    units = units.proj()

    if axs is None:
        fig, axs = plt.subplots(1, 2, figsize=(16, 6))
    assert axs.size == 2

    hemi = _get_units_hemisphere(units)

    period_starts = (experiment.Period
                     & 'period in ("sample", "delay", "response")').fetch(
                         'period_start')

    # no photostim:
    psth_n_l = psth.TrialCondition.get_cond_name_from_keywords(['_nostim', '_left'])[0]
    psth_n_r = psth.TrialCondition.get_cond_name_from_keywords(['_nostim', '_right'])[0]

    psth_n_l = (psth.UnitPsth * psth.TrialCondition & units
                & {'trial_condition_name': psth_n_l} & 'unit_psth is not NULL').fetch('unit_psth')
    psth_n_r = (psth.UnitPsth * psth.TrialCondition & units
                & {'trial_condition_name': psth_n_r} & 'unit_psth is not NULL').fetch('unit_psth')

    psth_s_l = psth.TrialCondition.get_cond_name_from_keywords(condition_name_kw + ['_stim_left'])[0]
    psth_s_r = psth.TrialCondition.get_cond_name_from_keywords(condition_name_kw + ['_stim_right'])[0]

    psth_s_l = (psth.UnitPsth * psth.TrialCondition & units
                & {'trial_condition_name': psth_s_l} & 'unit_psth is not NULL').fetch('unit_psth')
    psth_s_r = (psth.UnitPsth * psth.TrialCondition & units
                & {'trial_condition_name': psth_s_r} & 'unit_psth is not NULL').fetch('unit_psth')

    # get photostim duration and stim time (relative to go-cue)
    stim_trial_cond_name = psth.TrialCondition.get_cond_name_from_keywords(condition_name_kw + ['_stim'])[0]
    stim_time, stim_dur = _get_photostim_time_and_duration(units,
                                                           psth.TrialCondition().get_trials(stim_trial_cond_name))

    if hemi == 'left':
        psth_s_i = psth_s_l
        psth_n_i = psth_n_l
        psth_s_c = psth_s_r
        psth_n_c = psth_n_r
    else:
        psth_s_i = psth_s_r
        psth_n_i = psth_n_r
        psth_s_c = psth_s_l
        psth_n_c = psth_n_l

    _plot_avg_psth(psth_n_i, psth_n_c, period_starts, axs[0],
                   'Control')
    _plot_avg_psth(psth_s_i, psth_s_c, period_starts, axs[1],
                   'Photostim')

    # cosmetic
    ymax = max([ax.get_ylim()[1] for ax in axs])
    for ax in axs:
        ax.set_ylim((0, ymax))
        ax.set_xlim([_plt_xmin, _plt_xmax])

    # add shaded bar for photostim
    axs[1].axvspan(stim_time, stim_time + stim_dur, alpha=0.3, color='royalblue')


def plot_coding_direction(units, time_period=None, axs=None):
    _, proj_contra_trial, proj_ipsi_trial, time_stamps = psth.compute_CD_projected_psth(
        units.fetch('KEY'), time_period=time_period)

    period_starts = (experiment.Period & 'period in ("sample", "delay", "response")').fetch('period_start')

    if axs is None:
        fig, axs = plt.subplots(1, 1, figsize=(8, 6))

    # plot
    _plot_with_sem(proj_contra_trial, time_stamps, ax=axs, c='b')
    _plot_with_sem(proj_ipsi_trial, time_stamps, ax=axs, c='r')

    for x in period_starts:
        axs.axvline(x=x, linestyle = '--', color = 'k')
    # cosmetic
    axs.spines['right'].set_visible(False)
    axs.spines['top'].set_visible(False)
    axs.set_ylabel('CD projection (a.u.)')
    axs.set_xlabel('Time (s)')


def plot_paired_coding_direction(unit_g1, unit_g2, labels=None, time_period=None):
    """
    Plot trial-to-trial CD-endpoint correlation between CD-projected trial-psth from two unit-groups (e.g. two brain regions)
    Note: coding direction is calculated on selective units, contra vs. ipsi, within the specified time_period
    """
    _, proj_contra_trial_g1, proj_ipsi_trial_g1, time_stamps = psth.compute_CD_projected_psth(
        unit_g1.fetch('KEY'), time_period=time_period)
    _, proj_contra_trial_g2, proj_ipsi_trial_g2, time_stamps = psth.compute_CD_projected_psth(
        unit_g2.fetch('KEY'), time_period=time_period)

    period_starts = (experiment.Period & 'period in ("sample", "delay", "response")').fetch('period_start')

    if labels:
        assert len(labels) == 2
    else:
        labels = ('unit group 1', 'unit group 2')

    # plot projected trial-psth
    fig, axs = plt.subplots(1, 2, figsize=(16, 6))

    _plot_with_sem(proj_contra_trial_g1, time_stamps, ax=axs[0], c='b')
    _plot_with_sem(proj_ipsi_trial_g1, time_stamps, ax=axs[0], c='r')
    _plot_with_sem(proj_contra_trial_g2, time_stamps, ax=axs[1], c='b')
    _plot_with_sem(proj_ipsi_trial_g2, time_stamps, ax=axs[1], c='r')

    # cosmetic
    for ax, label in zip(axs, labels):
        for x in period_starts:
            ax.axvline(x=x, linestyle = '--', color = 'k')
        ax.spines['right'].set_visible(False)
        ax.spines['top'].set_visible(False)
        ax.set_ylabel('CD projection (a.u.)')
        ax.set_xlabel('Time (s)')
        ax.set_title(label)

    # plot trial CD-endpoint correlation
    p_start, p_end = time_period
    contra_cdend_1 = proj_contra_trial_g1[:, np.logical_and(time_stamps >= p_start, time_stamps < p_end)].mean(axis=1)
    contra_cdend_2 = proj_contra_trial_g2[:, np.logical_and(time_stamps >= p_start, time_stamps < p_end)].mean(axis=1)
    ipsi_cdend_1 = proj_ipsi_trial_g1[:, np.logical_and(time_stamps >= p_start, time_stamps < p_end)].mean(axis=1)
    ipsi_cdend_2 = proj_ipsi_trial_g2[:, np.logical_and(time_stamps >= p_start, time_stamps < p_end)].mean(axis=1)

    c_df = pd.DataFrame([contra_cdend_1, contra_cdend_2]).T
    c_df.columns = labels
    c_df['trial-type'] = 'contra'
    i_df = pd.DataFrame([ipsi_cdend_1, ipsi_cdend_2]).T
    i_df.columns = labels
    i_df['trial-type'] = 'ipsi'
    df = c_df.append(i_df)

    jplot = jointplot_w_hue(data=df, x=labels[0], y=labels[1], hue='trial-type', colormap=['b', 'r'],
                            figsize=(8, 6), fig=None, scatter_kws=None)
    jplot['fig'].show()

