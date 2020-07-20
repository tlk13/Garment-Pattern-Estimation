import os
from pathlib import Path
import requests

import torch
import wandb as wb

class WandbRunWrappper(object):
    """Class provides 
        * a convenient way to store wandb run info 
        * some functions & params shortcuts to access wandb functionality
        * for implemented functions, transparent workflow for finished and active (initialized) run 

        Wrapper currently does NOT wrap one-liners routinely called for active runs like wb.log(), wb.watch()  
    """
    def __init__(self, wandb_username, project_name='Train', run_name='Run', run_id=None, no_sync=False):
        """Init experiment tracking with wandb
            With no_sync==True, run won't sync with wandb cloud. 
            Note that resuming won't work for off-cloud runs as it requiers fetching files from the cloud"""

        self.checkpoint_filetag = 'checkpoint'
        self.final_filetag = 'fin_model_state'
        self.wandb_username = wandb_username
        
        self.project = project_name
        self.run_name = run_name
        self.run_id = run_id
        self.no_sync = False

        # cannot use wb.config, wb.run, etc. until run initialized & logging started & local path
        self.initialized = False  
        self.artifact = None

    # ----- start&stop ------
    def init_run(self, config={}):
        """Start wandb logging. 
            If run_id is known, run is automatically resumed.
            """
        if self.no_sync:
            os.environ['WANDB_MODE'] = 'dryrun'
            print('Experiment:Warning: run is not synced with wandb cloud')

        wb.init(name=self.run_name, project=self.project, config=config, resume=self.run_id)
        self.run_id = wb.run.id

        # upload these files as they are created https://docs.wandb.com/library/save
        wb.save('*' + self.checkpoint_filetag + '*')  
        wb.save(os.path.join(wb.run.dir, '*.json'))  
        # self.artifact = wb.Artifact(self.run_name, type='model')
        # wb.run.use_artifact(self.artifact)

        self.initialized = True

    def stop(self):
        """Stop wandb for current run. All logging finishes & files get uploaded"""
        if self.initialized:
            wb.join()
        self.initialized = False

    # -------- run info ------
    def last_epoch(self):
        """Id of the last epoch processed"""
        run = self._run_object()
        return run.summary['epoch']

    def data_info(self):
        """Info on the data setup from the run config:
            Split & batch size info """
        run = self._run_object()
        return run.config['data_split'], run.config['batch_size'], run.config['dataset']

    def NN_config(self):
        """Run configuration params of NeuralNetwork model"""
        run = self._run_object()
        return run.config['NN']

    def add_statistic(self, tag, info):
        """Add info the run summary (e.g. stats on test set)"""
        # different methods for on-going & finished runs
        if self.initialized:
            wb.run.summary[tag] = info
        else:
            run = self._run_object()
            run.summary[tag] = info
            run.summary.update()

    def add_config(self, tag, info):
        """Add new value to run config. Only for ongoing runs!"""
        if self.initialized:
            wb.config[tag] = info
        else:
            raise RuntimeError('WandbRunWrappper:Error:Cannot add config to finished run')

    def add_artifact(self, path, name, type):
        """Create a new wandb artifact and upload all the contents there"""

        run = wb.run if self.initialized else self._run_object()
        path = Path(path)

        artifact = wb.Artifact(name, type=type)
        if path.is_file():
            artifact.add_file(str(path))
        else:
            artifact.add_dir(str(path))
                    
        run.log_artifact(artifact)

    def is_finished(self):
        run = self._run_object()
        return run.state == 'finished'

    # ---- file info -----
    def checkpoint_filename(self):
        """Produce filename for the checkpoint of given epoch"""
        return '{}.pth'.format(self.checkpoint_filetag)

    def artifactname(self, tag, with_version=True, version=None):
        """Produce name for wandb artifact for current run with fiven tag"""
        basename = self.run_name + '_' + self.run_id + '_' + tag
        version_tag = ':v' + str(version) if version is not None else ':latest'

        return basename + version_tag if with_version else basename

    def final_filename(self):
        """Produce filename for the final model file (assuming PyTorch)"""
        return self.final_filetag + '.pth'

    def cloud_path(self):
        """Return virtual path to the current run on wandb could
            Implemented as a function to allow dynamic update of components with less bugs =)
        """
        if not self.run_id:
            raise RuntimeError('WbRunWrapper:Error:Need to know run id to get path in wandb could')
        return self.wandb_username + '/' + self.project + '/' + self.run_id

    def local_path(self):
        # if self.initialized:
        return Path(wb.run.dir)
        # raise RuntimeError('WbRunWrapper:Error:No local path exists: run is not initialized')

    # ----- working with files -------
    def load_checkpoint_file(self, to_path=None, version=None):
        """Load checkpoint file for given epoch from the cloud"""
        if not self.run_id:
            raise RuntimeError('WbRunWrapper:Error:Need to know run id to restore checkpoint from the could')
        try:
            art_path = self._load_artifact(self.artifactname(self.checkpoint_filetag, version=version))
            return torch.load(str(Path(art_path) / self.checkpoint_filename()))

        except (RuntimeError, requests.exceptions.HTTPError, wb.apis.CommError) as e:  # raised when file is corrupted or not found
            print('WbRunWrapper::Error::checkpoint from version \'{}\'is corrupted or lost: {}'.format(version if version else 'latest', e))
            raise e
    
    def load_final_model(self, to_path=None):
        """Load final model parameters file from the cloud if it exists"""
        if not self.run_id:
            raise RuntimeError('WbRunWrapper:Error:Need to know run id to restore final model from the could')
        try:
            art_path = self._load_artifact(self.artifactname(self.final_filetag), to_path=to_path)
            return torch.load(str(Path(art_path) / self.final_filename()))

        except (requests.exceptions.HTTPError, wb.apis.CommError):  # file not found
            raise RuntimeError('WbRunWrapper:Error:No file with final weights found in run {}'.format(self.cloud_path()))
    
    def save(self, state, save_name='checkpoint'):
        """Save given state dict as torch checkpoint to local run dir
            save_name parameter controls saving names (multiple could be used):
            * 'checkpoint' -> state is saved as a new checkpoint file
            * 'final' -> state is saved as final model file
            * all other options -> type is interpreted as filename, and state is simply saved with ginen filename"""

        if not self.initialized:
            raise RuntimeError('Experiment: cannot save files to non-active wandb runs')

        # Using artifacts to store important files for this run
        if save_name == 'checkpoint':
            artifact = wb.Artifact(self.artifactname(self.checkpoint_filetag, with_version=False), type='checkpoint')
            filename = self.checkpoint_filename()
        elif save_name == 'final':
            artifact = wb.Artifact(self.artifactname(self.final_filetag, with_version=False), type='result')
            filename = self.final_filename()
        else:
            artifact = wb.Artifact(self.artifactname(save_name, with_version=False), type='other')
            filename = save_name

        torch.save(state, self.local_path() / filename)
        artifact.add_file(str(self.local_path() / filename))
        wb.run.log_artifact(artifact)

    # ------- utils -------
    def _load_artifact(self, artifact_name, to_path=None):
        """Download a requested artifact withing current project. Return loaded path"""
        print('Experiment::Requesting artifacts: {}'.format(artifact_name))

        api = wb.Api({'project': self.project})
        artifact = api.artifact(name=artifact_name)
        filepath = artifact.download(str(to_path) if to_path else None)
        print('Experiment::Artifact saved to: {}'.format(filepath))

        return filepath

    def _run_object(self):
        """ Shortcut for getting reference to wandb api run object. 
            To uniformly access both ongoing & finished runs"""
        return wb.Api().run(self.cloud_path())