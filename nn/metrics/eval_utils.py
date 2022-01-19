"""
    List of metrics to evalute on a model and a dataset, along with pre-processing methods needed for such evaluation
"""

import torch

# My modules
from data import Garment3DPatternFullDataset as PatternDataset
from pattern_converter import InvalidPatternDefError


# ------- Model evaluation shortcut -------------
def eval_metrics(model, data_wrapper, section='test'):
    """Evalutes current model on the given dataset section"""
    device = model.device_ids[0] if hasattr(model, 'device_ids') else torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')
    
    model.to(device)
    model.eval()

    loss = model.module.loss if hasattr(model, 'module') else model.loss  # distinguish case of multi-gpu training

    if hasattr(loss, 'with_quality_eval'):
        loss.with_quality_eval = True  # force quality evaluation for losses that support it

    with torch.no_grad():
        loader = data_wrapper.get_loader(section)
        if isinstance(loader, dict):
            metrics_dict = {}
            for data_folder, loader in loader.items():
                metrics_dict[data_folder] = _eval_metrics_per_loader(model, loss, loader, device)
            return metrics_dict
        else:
            return _eval_metrics_per_loader(model, loss, loader, device)


def _eval_metrics_per_loader(model, loss, loader, device):
    """
    Evaluate model on given loader. 
    
    Secondary function -- it assumes that context is set up: torch.no_grad(), model device & mode, etc."""

    current_metrics = dict.fromkeys(['full_loss'], 0)
    counter = 0
    loader_iter = iter(loader)
    while True:  # DEBUG
        try:
            batch = next(loader_iter)  #  loader_iter.next()
        except StopIteration:
            break
        except InvalidPatternDefError as e:
            print(e)
            continue

        features, gt = batch['features'].to(device), batch['ground_truth']
        if gt is None or (hasattr(gt, 'nelement') and gt.nelement() == 0):  # assume reconstruction task
            gt = features

        # loss evaluation
        full_loss, loss_dict, _ = loss(model(features), gt, names=batch['name'])  # use names for cleaner errors when needed

        # summing up
        current_metrics['full_loss'] += full_loss
        for key, value in loss_dict.items():
            if key not in current_metrics:
                current_metrics[key] = 0  # init new metric
            current_metrics[key] += value

    # normalize & convert
    for metric in current_metrics:
        if isinstance(current_metrics[metric], torch.Tensor):
            current_metrics[metric] = current_metrics[metric].cpu().numpy()  # conversion only works on cpu
        current_metrics[metric] /= len(loader)

    return current_metrics


# ----- Utils -----
def eval_pad_vector(data_stats={}):
    # prepare padding vector used for panel padding 
    if data_stats:
        shift = torch.Tensor(data_stats['shift'])
        scale = torch.Tensor(data_stats['scale'])
        return (- shift / scale)
    else:
        return None
