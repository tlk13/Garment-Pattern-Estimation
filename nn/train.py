
from pathlib import Path

import torch
from torch.utils.data import DataLoader
import torchvision.transforms as transforms

# My modules
import dataloaders as dl
from trainer import Trainer
import nets

# Basic Parameters
datapath = r'D:\Data\CLOTHING\Learning Shared Shape Space_shirt_dataset_rest'
trainer = Trainer(
    datapath, 
    project_name='Test-Garments-Reconstruction', 
    run_name='refactoring-code')

trainer.init_randomizer()

#-------- DATA --------
# Initial load
shirts = dl.DatasetWrapper(dl.ParametrizedShirtDataSet(Path(datapath)))
# Data normalization
# mean, std = dl.get_mean_std(DataLoader(shirt_dataset, 100))
# shirt_dataset = dl.ParametrizedShirtDataSet(Path(data_location), transforms.Compose([dl.SampleToTensor(), dl.NormalizeInputfeatures(mean, std)]))

# Data load and split
shirts.new_split(valid_percent=10)
shirts.new_loaders(trainer.setup['batch_size'], shuffle_train=True)

print ('Split: {} / {}'.format(len(shirts.training), len(shirts.validation)))

# model
model = nets.ShirtfeaturesMLP()

# ----- Fit ---------

trainer.fit(model, shirts.loader_train, shirts.loader_validation)

# --------------- loss on validation set --------------
model.eval()
with torch.no_grad():
    valid_loss = sum([trainer.regression_loss(model(batch['features']), batch['pattern_params']) for batch in shirts.loader_validation]) 

print ('Validation loss: {}'.format(valid_loss))


# save prediction for validation to file
model.eval()
with torch.no_grad():
    batch = next(iter(shirts.loader_validation))    # might have some issues, see https://github.com/pytorch/pytorch/issues/1917
    shirts.dataset.save_prediction_batch(model(batch['features']), batch['name'])