"""
    This script uses results produced by save_latent_encodings.py
    Separation in two skipts was simply needed to experiment with visual style without re-running the net every time
"""

from pathlib import Path
import torch
import pickle
import numpy as np
from datetime import datetime

# Do avoid a need for changing Evironmental Variables outside of this script
import os,sys,inspect
currentdir = os.path.dirname(os.path.realpath(__file__) )
parentdir = os.path.dirname(currentdir)
sys.path.insert(0,parentdir) 

# visualization
from sklearn.manifold import TSNE
import matplotlib.pyplot as plt

# my
import customconfig
import data
import nets
from trainer import Trainer
from experiment import WandbRunWrappper


def load_model_loader(experiment, datasets_path, subset='test'):
    """
        Return NN model object and a test set loader accosiated with given experiment
    """
    # -------- data -------
    # data_config also contains the names of datasets to use
    split, batch_size, data_config = experiment.data_info()  # note that run is not initialized -- we use info from finished run
    data_config.update({'obj_filetag': 'sim'})  # , 'max_datapoints_per_type': 300})

    dataset = data.Garment3DPatternFullDataset(
        datasets_path, data_config, gt_caching=True, feature_caching=True)
    datawrapper = data.DatasetWrapper(dataset, known_split=split, batch_size=batch_size)
    test_loader = datawrapper.get_loader(subset)

    # ----- Model -------
    model = nets.GarmentFullPattern3D(dataset.config, experiment.NN_config())
    model.load_state_dict(experiment.load_best_model()['model_state_dict'])

    return test_loader, model


def get_encodings(model, loader, save_to=None):
    """
        Get latent space encodings on the test set from the given experiment (defines both dataset and the model)
        Save then to given folder if provided
    """

    # get all encodings
    device = torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')
    model.to(device)
    model.eval()
    all_garment_encodings = []
    all_panel_encodings = []
    classes_garments = []
    classes_panels = []
    with torch.no_grad():
        for batch in loader:
            features = batch['features'].to(device)
            garment_encodings = model.forward_encode(features)

            panel_encodings = model.forward_pattern_decode(garment_encodings)

            all_garment_encodings.append(garment_encodings)
            all_panel_encodings.append(panel_encodings)

            classes_garments += batch['data_folder']
            for pattern_id in range(len(batch['data_folder'])):
                # copy the folder of pattern to every panel in it's patten
                classes_panels += [batch['data_folder'][pattern_id] for _ in range(model.max_pattern_size)]

    all_garment_encodings = torch.cat(all_garment_encodings).cpu().numpy()
    all_panel_encodings = torch.cat(all_panel_encodings).cpu().numpy()

    if save_to is not None:
        np.save(save_to / 'enc_garments.npy', all_garment_encodings)
        np.save(save_to / 'enc_panels.npy', all_panel_encodings)
        with open(save_to / 'data_folders_garments.pkl', 'wb') as fp:
            pickle.dump(classes_garments, fp)
        with open(save_to / 'data_folders_panels.pkl', 'wb') as fp:
            pickle.dump(classes_panels, fp)
    
    return all_garment_encodings, classes_garments, all_panel_encodings, classes_panels


def load_enc_from_files(encodings_folder, enc_tag='garments'):
    """
        Load serialized encodings for particular type of encoding
        Supported tags (aka types): {'garments', 'panels'}
    """

    all_encodings = np.load(encodings_folder / ('enc_' + enc_tag + '.npy'))
    with open(encodings_folder / ('data_folders_' + enc_tag + '.pkl'), 'rb') as fp:
        classes = pickle.load(fp)

    print(all_encodings.shape, len(classes))

    return all_encodings, classes


def tsne_plot(all_encodings, classes, save_to='./', name_tag='enc', interactive_mode=False, dpi=300):
    """
        Plot encodings using TSNE dimentionality reduction
    """
    # https://towardsdatascience.com/visualising-high-dimensional-datasets-using-pca-and-t-sne-in-python-8ef87e7915b
    # https://scipy-lectures.org/packages/scikit-learn/auto_examples/plot_tsne.html
    tsne = TSNE(n_components=2, random_state=0)
    enc_2d = tsne.fit_transform(all_encodings)

    # ----- Visualize ------
    # update class labeling
    # This is hardcoded stuff because it's mostly needed for final presentation
    # TODO avoid hardcoding dataset names (or template names) -- picking up from dataset properties?
    mapping = {
        'tee_sleeveless': 'Shirts and dresses',
        'tee': 'Shirts and dresses',
        'jacket': 'Jacket',
        'jacket_hood': 'Open Hoody',
        'pants_straight_sides': 'Pants',
        'wb_pants_straight': 'Waistband pants',
        'jumpsuit_sleeveless': 'Sleeveless Jumpsuit',
        'skirt_4_panels': '4-panel Skirts',
        'skirt_2_panels': '2-panel Skirts',
        'skirt_8_panels': '8-panel Skirts',
        'dress_sleeveless': 'Sleeveless Dresses ',
        'wb_dress_sleeveless': 'Sleeveless Waistband dresses'
    }
    classes = np.array([mapping.get(label, 'Unknown') for label in classes])

    # define colors
    colors = {
        'Shirts and dresses': (0.747, 0.236, 0.048), # (190, 60, 12)
        'Jacket': (0.4793117642402649, 0.10461537539958954, 0.0),
        'Open Hoody': (0.746999979019165, 0.28518322110176086, 0.11503798514604568), 
        '8-panel Skirts': (0.048, 0.0290, 0.747),  # (12, 74, 190)
        '4-panel Skirts': (0.048, 0.0290, 0.747),  # (12, 74, 190)
        '2-panel Skirts': (0.24227915704250336, 0.6172128915786743, 1.0),  
        'Pants': (0.025, 0.354, 0.152),  # (6, 90. 39)
        'Jumpsuit': (0.6104, 0.3023, 0.0872),  # (105,52,15)
        'Waistband dresses': (0.2, 0.007, 0.192),  
        'Dresses': (0.527, 0.0, 0.0),  # (134,0,0)
        'Waistband pants': (0.250900000333786, 0.3528999984264374, 0.13330000638961792), 
        'Unknown': (0.15, 0.15, 0.15)
    }

    # plot
    fig, ax = plt.subplots()

    # plot data
    for label, color in colors.items():
        if len(enc_2d[classes == label, 0] > 0):  # skip unused classes
            plt.scatter(
                enc_2d[classes == label, 0], enc_2d[classes == label, 1], 
                color=color, label=label,
                edgecolors=None, alpha=0.5, s=17)
            if label == 'Unknown':
                print('TSNE_plot::Warning::Some labels are unknown and thus colored with Dark Grey')
    plt.legend()

    # Axes colors
    # https://stackoverflow.com/questions/7778954/elegantly-changing-the-color-of-a-plot-frame-in-matplotlib/7944576
    plt.setp(ax.spines.values(), color='#737373')
    ax.tick_params(axis='x', colors='#737373')
    ax.tick_params(axis='y', colors='#737373')

    # plt.savefig('D:/MyDocs/GigaKorea/SIGGRAPH2021 submission materials/Latent space/tsne.pdf', dpi=300, bbox_inches='tight')

    plt.savefig(save_to / ('tsne_' + name_tag + '.pdf'), dpi=dpi, bbox_inches='tight')
    plt.savefig(save_to / ('tsne_' + name_tag + '.jpg'), dpi=dpi, bbox_inches='tight')
    if interactive_mode:
        plt.show()
    
    print('Info::Saved TSNE plot for {}'.format(name_tag))


if __name__ == '__main__':
    system_info = customconfig.Properties('./system.json')

    experiment = WandbRunWrappper(
        system_info['wandb_username'],
        project_name='Garments-Reconstruction', 
        run_name='tee-skirt-dresses-300-server', 
        run_id='3ffg3xdy')  # finished experiment

    if not experiment.is_finished():
        print('Warning::Evaluating unfinished experiment')

    out_folder = Path(system_info['output']) / ('tsne_' + experiment.run_name + '_' + datetime.now().strftime('%y%m%d-%H-%M-%S'))
    out_folder.mkdir(parents=True, exist_ok=True)

    # extract encodings
    data_loader, model = load_model_loader(experiment, system_info['datasets_path'], 'test')

    garment_enc, garment_classes, panel_enc, panel_classes = get_encodings(model, data_loader, out_folder)

    # if loading from file
    # encodings_folder_name = 'tsne_teesl-pants-Jump-300-server_210325-13-33-29'
    # garment_enc, garment_classes = load_enc_from_files(Path(system_info['output']) / encodings_folder_name, 'garments')
    # panel_enc, panel_classes = load_enc_from_files(Path(system_info['output']) / encodings_folder_name, 'panels')

    # save plots
    tsne_plot(garment_enc, garment_classes, out_folder, 'garments', True, dpi=600)
    tsne_plot(panel_enc, panel_classes, out_folder, 'panels', True, dpi=600)

