#!/usr/bin/env python3
import os, sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from datetime import datetime
from dateutil.tz import tzlocal
import pytz
import re
import numpy as np
import json
import pandas as pd

from pipeline import (lab, experiment, ephys, psth, tracking, virus)
import pynwb
from pynwb import NWBFile, NWBHDF5IO

# ============================== SET CONSTANTS ==========================================
default_nwb_output_dir = os.path.join('data', 'NWB 2.0')
zero_zero_time = datetime.strptime('00:00:00', '%H:%M:%S').time()  # no precise time available
hardware_filter = 'Bandpass filtered 300-6K Hz'
institution = 'Janelia Research Campus'


def export_to_nwb(session_key, nwb_output_dir=default_nwb_output_dir, save=False, overwrite=False):

    this_session = (experiment.Session & session_key).fetch1()
    print(f'Exporting to NWB 2.0 for session: {this_session}...')
    # ===============================================================================
    # ============================== META INFORMATION ===============================
    # ===============================================================================

    # -- NWB file - a NWB2.0 file for each session
    nwbfile = NWBFile(identifier='_'.join(
        ['ANM' + str(this_session['subject_id']),
         this_session['session_date'].strftime('%Y-%m-%d'),
         str(this_session['session'])]),
        session_description='',
        session_start_time=datetime.combine(this_session['session_date'], zero_zero_time),
        file_create_date=datetime.now(tzlocal()),
        experimenter=this_session['username'],
        institution=institution)
    # -- subject
    subj = (lab.Subject & session_key).fetch1()
    nwbfile.subject = pynwb.file.Subject(
        subject_id=str(this_session['subject_id']),
        genotype=' x '.join((lab.Subject.GeneModification
                             & subj).fetch('gene_modification')),
        sex=subj['sex'],
        species=subj['species'],
        date_of_birth=datetime.combine(subj['date_of_birth'], zero_zero_time) if subj['date_of_birth'] else None)
    # -- virus
    nwbfile.virus = json.dumps([{k: str(v) for k, v in virus_injection.items() if k not in subj}
                                for virus_injection in virus.VirusInjection * virus.Virus & session_key])

    # ===============================================================================
    # ======================== EXTRACELLULAR & CLUSTERING ===========================
    # ===============================================================================

    """
    In the event of multiple probe recording (i.e. multiple probe insertions), the clustering results 
    (and the associated units) are associated with the corresponding probe. 
    Each probe insertion is associated with one ElectrodeConfiguration (which may define multiple electrode groups)
    """

    dj_insert_location = ephys.ProbeInsertion.InsertionLocation * experiment.BrainLocation

    for probe_insertion in ephys.ProbeInsertion & session_key:
        electrode_config = (lab.ElectrodeConfig & probe_insertion).fetch1()

        electrode_groups = {}
        for electrode_group in lab.ElectrodeConfig.ElectrodeGroup & electrode_config:
            electrode_groups[electrode_group['electrode_group']] = nwbfile.create_electrode_group(
                name=electrode_config['electrode_config_name'] + '_g' + str(electrode_group['electrode_group']),
                description='N/A',
                device=nwbfile.create_device(name=electrode_config['probe']),
                location=json.dumps({k: str(v) for k, v in (dj_insert_location & session_key).fetch1().items()
                                     if k not in dj_insert_location.primary_key}))

        for chn in (lab.ElectrodeConfig.Electrode * lab.Probe.Electrode & electrode_config).fetch(as_dict=True):
            nwbfile.add_electrode(id=chn['electrode'],
                                  group=electrode_groups[chn['electrode_group']],
                                  filtering=hardware_filter,
                                  imp=-1.,
                                  x=chn['x_coord'] if chn['x_coord'] else np.nan,
                                  y=chn['y_coord'] if chn['y_coord'] else np.nan,
                                  z=chn['z_coord'] if chn['z_coord'] else np.nan,
                                  location=electrode_groups[chn['electrode_group']].location)

        # --- unit spike times ---
        nwbfile.add_unit_column(name='quality', description='unit quality from clustering')
        nwbfile.add_unit_column(name='posx', description='estimated x position of the unit relative to probe (0,0)')
        nwbfile.add_unit_column(name='posy', description='estimated y position of the unit relative to probe (0,0)')
        nwbfile.add_unit_column(name='amp', description='unit amplitude')
        nwbfile.add_unit_column(name='snr', description='unit signal-to-noise')
        nwbfile.add_unit_column(name='cell_type', description='cell type (e.g. fast spiking or pyramidal)')

        for unit in (ephys.Unit * ephys.UnitCellType & probe_insertion).fetch(as_dict=True):
            # make an electrode table region (which electrode(s) is this unit coming from)
            nwbfile.add_unit(id=unit['unit'],
                             electrodes=[unit['electrode']],
                             electrode_group=electrode_groups[unit['electrode_group']],
                             quality=unit['unit_quality'],
                             posx=unit['unit_posx'],
                             posy=unit['unit_posy'],
                             amp=unit['unit_amp'] if unit['unit_amp'] else np.nan,
                             snr=unit['unit_snr'] if unit['unit_amp'] else np.nan,
                             cell_type=unit['cell_type'],
                             spike_times=unit['spike_times'],
                             waveform_mean=np.mean(unit['waveform'], axis=0),
                             waveform_sd=np.std(unit['waveform'], axis=0))

    # ===============================================================================
    # ============================= BEHAVIOR TRACKING ===============================
    # ===============================================================================

    if tracking.LickTrace * experiment.SessionTrial & session_key:
        # re-concatenating trialized tracking traces
        lick_traces, time_vecs, trial_starts = (tracking.LickTrace * experiment.SessionTrial & session_key).fetch(
            'lick_trace', 'lick_trace_timestamps', 'start_time')
        behav_acq = pynwb.behavior.BehavioralTimeSeries(name='BehavioralTimeSeries')
        nwbfile.add_acquisition(behav_acq)
        behav_acq.create_timeseries(name='lick_trace', unit='a.u.', conversion=1.0,
                                    data=np.hstack(lick_traces),
                                    timestamps=np.hstack(time_vecs + trial_starts.astype(float)))

    # ===============================================================================
    # ============================= PHOTO-STIMULATION ===============================
    # ===============================================================================
    stim_sites = {}
    for photostim in experiment.Photostim * experiment.BrainLocation * lab.PhotostimDevice & session_key:

        stim_device = (nwbfile.get_device(photostim['photostim_device'])
                       if photostim['photostim_device'] in nwbfile.devices
                       else nwbfile.create_device(name=photostim['photostim_device']))

        stim_site = pynwb.ogen.OptogeneticStimulusSite(
            name=photostim['brain_location_name'],
            device=stim_device,
            excitation_lambda=float(photostim['excitation_wavelength']),
            location=json.dumps({k: str(v) for k, v in photostim.items()
                                if k in dj_insert_location.heading.names and k not in dj_insert_location.primary_key}),
            description='')
        nwbfile.add_ogen_site(stim_site)
        stim_sites[photostim['photo_stim']] = stim_site

    # re-concatenating trialized photostim traces
    dj_photostim = (experiment.PhotostimTrace * experiment.SessionTrial * experiment.PhotostimEvent
                    * experiment.Photostim * experiment.BrainLocation & session_key)

    for photo_stim, stim_site in stim_sites.items():
        if dj_photostim & {'photo_stim': photo_stim}:
            aom_input_trace, laser_power, time_vecs, trial_starts, brain_location_name = (
                    dj_photostim & {'photo_stim': photo_stim}).fetch(
                'aom_input_trace', 'laser_power', 'photostim_timestamps', 'start_time', 'brain_location_name')

            aom_series = pynwb.ogen.OptogeneticSeries(
                name=stim_site.name + '_aom_input_trace',
                site=stim_site, unit='mW', resolution=0.0, conversion=1e-6,
                data=np.hstack(aom_input_trace),
                timestamps=np.hstack(time_vecs + trial_starts.astype(float)))
            laser_series = pynwb.ogen.OptogeneticSeries(
                name=stim_site.name + '_laser_power',
                site=stim_site, unit='mW', resolution=0.0, conversion=1e-6,
                data=np.hstack(laser_power),
                timestamps=np.hstack(time_vecs + trial_starts.astype(float)))

            nwbfile.add_stimulus(aom_series)
            nwbfile.add_stimulus(laser_series)

    # ===============================================================================
    # =============================== BEHAVIOR TRIALS ===============================
    # ===============================================================================

    # =============== TrialSet ====================
    # NWB 'trial' (of type dynamic table) by default comes with three mandatory attributes: 'start_time' and 'stop_time'
    # Other trial-related information needs to be added in to the trial-table as additional columns (with column name
    # and column description)

    dj_trial = experiment.SessionTrial * experiment.BehaviorTrial
    skip_adding_columns = experiment.Session.primary_key + ['trial_uid']

    if experiment.SessionTrial & session_key:
        # Get trial descriptors from TrialSet.Trial and TrialStimInfo
        trial_columns = [{'name': tag,
                          'description': re.sub('\s+:|\s+', ' ', re.search(
                              f'(?<={tag})(.*)', str(dj_trial.heading)).group()).strip()}
                         for tag in dj_trial.heading.names
                         if tag not in skip_adding_columns + ['start_time', 'stop_time']]

        # Add new table columns to nwb trial-table for trial-label
        for c in trial_columns:
            nwbfile.add_trial_column(**c)

        # Add entry to the trial-table
        for trial in (dj_trial & session_key).fetch(as_dict=True):
            trial['start_time'] = float(trial['start_time'])
            trial['stop_time'] = float(trial['stop_time']) if trial['stop_time'] else 5.0
            [trial.pop(k) for k in skip_adding_columns]
            nwbfile.add_trial(**trial)

    # ===============================================================================
    # =============================== BEHAVIOR TRIAL EVENTS ==========================
    # ===============================================================================

    behav_event = pynwb.behavior.BehavioralEvents(name='BehavioralEvents')
    nwbfile.add_acquisition(behav_event)

    for trial_event_type in (experiment.TrialEventType & experiment.TrialEvent & session_key).fetch('trial_event_type'):
        event_times, trial_starts = (experiment.TrialEvent * experiment.SessionTrial
                                     & session_key & {'trial_event_type': trial_event_type}).fetch(
            'trial_event_time', 'start_time')
        if len(event_times) > 0:
            event_times = np.hstack(event_times.astype(float) + trial_starts.astype(float))
            behav_event.create_timeseries(name=trial_event_type, unit='a.u.', conversion=1.0,
                                          data=np.full_like(event_times, 1),
                                          timestamps=event_times)

    photostim_event_time, trial_starts, photo_stim, power, duration = (
            experiment.PhotostimEvent * experiment.SessionTrial & session_key).fetch(
        'photostim_event_time', 'start_time', 'photo_stim', 'power', 'duration')

    if len(photostim_event_time) > 0:
        behav_event.create_timeseries(name='photostim_start_time', unit='a.u.', conversion=1.0,
                                      data=power,
                                      timestamps=photostim_event_time.astype(float) + trial_starts.astype(float),
                                      control=photo_stim.astype('uint8'), control_description=stim_sites)
        behav_event.create_timeseries(name='photostim_stop_time', unit='a.u.', conversion=1.0,
                                      data=np.full_like(photostim_event_time, 0),
                                      timestamps=photostim_event_time.astype(float) + duration.astype(float) + trial_starts.astype(float),
                                      control=photo_stim.astype('uint8'), control_description=stim_sites)

    # =============== Write NWB 2.0 file ===============
    if save:
        save_file_name = ''.join([nwbfile.identifier, '.nwb'])
        if not os.path.exists(nwb_output_dir):
            os.makedirs(nwb_output_dir)
        if not overwrite and os.path.exists(os.path.join(nwb_output_dir, save_file_name)):
            return nwbfile
        with NWBHDF5IO(os.path.join(nwb_output_dir, save_file_name), mode = 'w') as io:
            io.write(nwbfile)
            print(f'Write NWB 2.0 file: {save_file_name}')

    return nwbfile


# ============================== EXPORT ALL ==========================================

if __name__ == '__main__':
    if len(sys.argv) > 1:
        nwb_outdir = sys.argv[1]
    else:
        nwb_outdir = default_nwb_output_dir

    for skey in experiment.Session.fetch('KEY'):
        export_to_nwb(skey, nwb_output_dir=nwb_outdir, save=True)
