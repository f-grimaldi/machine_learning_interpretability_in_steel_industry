import sys
import os
sys.path.append('\\'.join(os.getcwd().split('\\')[:-1])+'\\src')
from dataset import SlidingWindow
from utils import get_default_params

import numpy as np
import matplotlib.pyplot as plt

import torch
import time
import argparse

from PIL import Image
from tqdm import tqdm
from torch import nn, optim
from torch.utils.data import dataloader
from torchvision import transforms, models
from sklearn.metrics import accuracy_score, f1_score, balanced_accuracy_score
from sklearn.utils import shuffle

def get_argparse():
    # 1. Set argument
    parser = argparse.ArgumentParser(description='Explain SteelNetClassifier')
    # 1.a) General args
    parser.add_argument('--model_output_path', type=str)
    parser.add_argument('--train_input_path',
                        type=str,            default='../data/multiData/X_train.pth')
    parser.add_argument('--train_label_path',
                        type=str,            default='../data/multiData/y_train.pth')
    parser.add_argument('--train_mask_path',
                        type=str,            default='../data/multiData/M_train.pth')
    parser.add_argument('--train_augmented_input_path',
                        type=str,            default='../data/multiData/X_train_aug.pth')
    parser.add_argument('--train_augmented_label_path',
                        type=str,            default='../data/multiData/y_train_aug.pth')
    parser.add_argument('--train_augmented_mask_path',
                        type=str,            default='../data/multiData/M_train_aug.pth')
    parser.add_argument('--val_input_path',
                        type=str,            default='../data/multiData/X_val.pth')
    parser.add_argument('--val_label_path',
                        type=str,            default='../data/multiData/y_val.pth')
    parser.add_argument('--val_mask_path',
                        type=str,            default='../data/multiData/M_val.pth')
    parser.add_argument('--use_sliding_window',
                        action='store_true')
    parser.add_argument('--reduce_class_zero',
                        type=float,          default=0.50)
    parser.add_argument('--use_augmentation',
                        action='store_true')
    parser.add_argument('--cpu',
                        action = 'store_true')
    parser.add_argument('--reduced',
                        type=int,            default=-1)
    parser.add_argument('--n_output',
                        type=int,            default=5)
    parser.add_argument('--batch_size',
                        type=int,            default=10)
    parser.add_argument('--lr',
                        type=float,          default=0.0001)
    parser.add_argument('--patience',
                        type=int,            default=5)
    parser.add_argument('--epochs',
                        type=int,            default=60)
    parser.add_argument('--noise_coeff',
                        type=float,          default=0.15)
    parser.add_argument('--weight_loss',
                        action='store_true')
    parser.add_argument('--save_last',
                        action='store_true')
    parser.add_argument('--vanilla',
                        action='store_true')

    args = parser.parse_args()
    return args

def get_model(args, device):
    if not args.vanilla:
        net = models.squeezenet1_1(pretrained=True)
    else:
        net = models.squeezenet1_1(pretrained=False)
    if args.reduced > 0:
        filters = {10: 384, 9:256, 8:256, 7:256}
        net.features = net.features[:args.reduced]
        net.classifier[1] = nn.Conv2d(filters[args.reduced],
                                      1000,
                                      kernel_size = (1, 1),
                                      stride = (1, 1))

    net.classifier = nn.Sequential(*net.classifier, nn.Flatten(),
                                    nn.Linear(1000, args.n_output))
    print(net)
    net = net.to(device)
    return net

def sliding_window(X, y, M, batch_size):
    sliding = SlidingWindow(X, y, M)
    X_slided = torch.empty((X.shape[0]*6, 3, 64, 64))
    y_slided = torch.empty((X.shape[0]*6)).long()
    M_slided = torch.empty((X.shape[0]*6, 64, 64)).long()
    loader = dataloader.DataLoader(sliding, batch_size)

    for n, batch in tqdm(enumerate(loader)):
        X_batch, y_batch, M_batch = batch
        bs = y_batch.shape[0]
        X_slided[n*6*batch_size:n*6*batch_size + bs*6] = X_batch.view(bs*6, 3, 64, 64)
        y_slided[n*6*batch_size:n*6*batch_size + bs*6] = y_batch.view(bs*6)
        M_slided[n*6*batch_size:n*6*batch_size + bs*6] = M_batch.view(bs*6, 64, 64)
    mean = X_slided.mean(axis=(1, 2, 3))
    X_slided = X_slided[mean > -1.80]
    y_slided = y_slided[mean > -1.80]
    M_slided = M_slided[mean > -1.80]
    """
    if args.reduce_class_zero != 0:
        X_slided_0_
    """
    return X_slided, y_slided, M_slided

def use_noise(X, y, noise_coeff, device):
    if noise_coeff == 0:
        return X, y
    else:
        X = torch.cat([X, X + torch.randn(*list(X.shape)).to(device)*noise_coeff])
        y = torch.cat([y, y])
        return X, y

def get_treshold(t=0.5):
    y_pred_s = y_score.copy()
    y_pred_s[y_score > t] = 0
    y_pred_s[y_score <= t] = 1
    return y_pred_s, f1_score(y_true, y_pred_s, average='macro')

def main():

    ### 1. Set parameters
    args = get_argparse()
    device = torch.device('cuda') if torch.cuda.is_available() else torch.device('cpu')
    params = get_default_params()
    print('Device: {}'.format(device))
    print('Arguments:\n{}'.format(args))
    print('Parameters:\n{}'.format(params))

    torch.save(torch.tensor([1]), args.model_output_path)
    ### 2. Load data
    X_train = torch.load(args.train_input_path)
    y_train = torch.load(args.train_label_path)

    X_val= torch.load(args.val_input_path)
    y_val = torch.load(args.val_label_path)

    if args.use_augmentation or args.use_sliding_window:
        M_train = torch.load(args.train_mask_path)

    ### 2.a Load also augmented images
    if args.use_augmentation:
        print('Using augmentation for under represented class:')
        X_train_aug = torch.load(args.train_augmented_input_path)
        y_train_aug = torch.load(args.train_augmented_label_path)
        M_train_aug = torch.load(args.train_augmented_mask_path)
        X_train = torch.cat([X_train, X_train_aug])
        y_train = torch.cat([y_train, y_train_aug])
        M_train = torch.cat([M_train, M_train_aug])
        X_train, y_train, M_train = shuffle(X_train, y_train, M_train)
        print('\tAdded {} new examples'.format(X_train_aug.shape[0]))

    ### 2.b Use SlidingWindow
    if args.use_sliding_window:
        M_val = torch.load(args.val_mask_path)
        print('Using sliding windows:')
        print('\tBefore procedure images have shape: {}'.format(X_train.shape))
        X_train, y_train, M_train = sliding_window(X_train,
                                                   y_train,
                                                   M_train,
                                                   args.batch_size*2)
        X_val, y_val, M_val = sliding_window(X_val,
                                             y_val,
                                             M_val,
                                             args.batch_size*2)
        print('\tAfter procedure images have shape: {}'.format(X_train.shape))


    ### 3. Load model
    net = get_model(args, device)

    ### 4. Train model
    ### 4.a Define Optimizer
    optimizer = optim.Adam(net.parameters(), lr=args.lr)
    ### 4.b Use weight or unweighted loss
    if args.weight_loss:
        w = [1/y_val[y_val == i].shape[0] for i in range(args.n_output)]
        loss_fn = nn.CrossEntropyLoss(torch.tensor(w).to(device))
    else:
        loss_fn = nn.CrossEntropyLoss()
    ### 4.c Set scheduler
    #lr_scheduler = optim.lr_scheduler.StepLR(optimizer, step_size=7, gamma=0.2)

    ### 4.d Init training variables
    train_loss_curve, valid_loss_curve = [], []
    train_accuracy, valid_accuracy = [], []
    train_f1, valid_f1 = [], []
    train_bal_accuracy, valid_bal_accuracy = [], []

    best_loss = np.inf
    patience = 0
    max_patience = args.patience
    bs = args.batch_size

    ### 4.e Run an epoch
    for ep in range(args.epochs):
        batch_train_loss, batch_valid_loss = [], []
        batch_train_acc, batch_valid_acc = [], []
        batch_train_f1, batch_valid_f1 = [], []
        batch_train_bal_acc, batch_valid_bal_acc = [], []
        time.sleep(0.1)

        ### TRAIN
        net.train()
        for n in tqdm(range(X_train.shape[0]//bs)):
            optimizer.zero_grad()
            X, y = X_train[n*bs:(n+1)*bs].to(device), y_train[n*bs:(n+1)*bs].to(device).long()
            X, y = use_noise(X, y, args.noise_coeff, device)

            out = net(X)
            loss = loss_fn(out, y)
            loss.backward()
            optimizer.step()

            y_pred = np.argmax(out.detach().cpu().numpy(), axis=1)
            y_true = y.cpu().numpy()
            batch_train_loss.append(float(loss))
            batch_train_acc.append(float(accuracy_score(y_true, y_pred)))
            batch_train_bal_acc.append(float(balanced_accuracy_score(y_true, y_pred)))
            batch_train_f1.append(float(f1_score(y_true, y_pred, average='weighted')))

        ### VALIDATION
        time.sleep(0.1)
        with torch.no_grad():
            net.eval()
            for n in tqdm(range(X_val.shape[0]//bs)):
                X, y = X_val[n*bs:(n+1)*bs].to(device), y_val[n*bs:(n+1)*bs].to(device).long()
                out = net(X)
                loss = loss_fn(out, y)

                y_pred = np.argmax(out.detach().cpu().numpy(), axis=1)
                batch_valid_loss.append(float(loss))
                batch_valid_acc.append(float(accuracy_score(y.cpu().numpy(), y_pred)))
                batch_valid_bal_acc.append(float(balanced_accuracy_score(y.cpu().numpy(), y_pred)))
                batch_valid_f1.append(float(f1_score(y.cpu().numpy(), y_pred, average='weighted')))

        #lr_scheduler.step()

        ### Check results
        train_loss_curve.append(np.mean(batch_train_loss))
        train_accuracy.append(np.mean(batch_train_acc))
        train_bal_accuracy.append(np.mean(batch_train_bal_acc))
        train_f1.append(np.mean(batch_train_f1))

        valid_loss_curve.append(np.mean(batch_valid_loss))
        valid_accuracy.append(np.mean(batch_valid_acc))
        valid_f1.append(np.mean(batch_valid_f1))
        valid_bal_accuracy.append(np.mean(batch_valid_bal_acc))

        if valid_loss_curve[-1] < best_loss:
            best_loss = valid_loss_curve[-1]
            print('New best parameters have been found. Saving them in {}'.format(args.model_output_path))
            torch.save(net.state_dict(), args.model_output_path)
            patience = 0
        else:
            patience += 1
            time.sleep(0.1)
        print('Epoch: {}'.format(ep + 1))
        print('Train:\tCrossEntropyLoss: {:.4f}\tAccuracy: {:.4f}'.format(train_loss_curve[-1], train_accuracy[-1]), end = '\t')
        print('F1 Score: {:.4f}\tBalanced Accuracy:\t{:.4f}'.format(train_f1[-1], train_bal_accuracy[-1]))
        print('Valid:\tCrossEntropyLoss: {:.4f}\tAccuracy: {:.4f}'.format(valid_loss_curve[-1], valid_accuracy[-1]), end = '\t')
        print('F1 Score: {:.4f}\tBalanced Accuracy:\t{:.4f}'.format(valid_f1[-1], valid_bal_accuracy[-1]))
        time.sleep(0.1)

        if patience >= max_patience:
            print('Max patience has been reached. Stopping training...')
            break


    ### 5. Plot loss curves and accuracies

    fig, ax = plt.subplots(1, 2, figsize=(20, 5))
    ax[0].plot(train_loss_curve, label='Train Loss')
    ax[0].plot(valid_loss_curve, label='Validation Loss')
    ax[0].legend()
    ax[0].grid()
    ax[0].set_title('Loss curve')
    ax[0].set_xlabel('Epoch')
    ax[0].set_ylabel('Loss')
    ax[1].plot(train_accuracy, label='Train Accuracy')
    ax[1].plot(valid_accuracy, label='Validation Accuracy')
    ax[1].legend()
    ax[1].grid()
    ax[1].set_title('Accuracy curve')
    ax[1].set_xlabel('Epoch')
    ax[1].set_ylabel('Accuracy')
    plt.show()
    #
    # y_pred = []
    # y_true = []
    # y_score = []
    # batch_size = 10
    # with torch.no_grad():
    #     net.eval()
    #     for n in tqdm(range(X_val.shape[0]//batch_size)):
    #         X, y = X_val[n*batch_size:(n+1)*batch_size].to(device), y_val[n*batch_size:(n+1)*batch_size].to(device).long()
    #         out = net(X)
    #         y_score = np.concatenate([y_score, nn.Softmax(dim=1)(out).detach().cpu().numpy().reshape(-1)])
    #         y_pred = np.concatenate([y_pred, np.argmax(out.detach().cpu().numpy(), axis=1)])
    #         y_true = np.concatenate([y_true, y.cpu().numpy()])
    #
    # tpr, fpr, threshold = roc_curve(y_true, y_score)
    # auc_score = auc(fpr, tpr)
    # print('METRICS WITH 0.5 AS THRESHOLD')
    # print('-----------------------------')
    # print('Accuracy:\t{:.4f}'.format(accuracy_score(y_true, y_pred)))
    # print('F1 Score:\t{:.4f}'.format(f1_score(y_true, y_pred, average='macro')))
    # print('AUC Score:\t{:.4f}'.format(auc_score))
    #
    #
    #
    # best_treshold = np.argmax([get_treshold(t=i)[1] for i in np.arange(0, 1, step=0.05)])*0.05
    # y_pred_best = get_treshold(t=best_treshold)[0]
    #
    # accuracy = accuracy_score(y_true, y_pred_best)
    # f1 = f1_score(y_true, y_pred_best, average='macro')
    # print('METRICS WITH {:.2f} THRESHOLD'.format(best_treshold))
    # print('-----------------------------')
    # print('Accuracy:\t{:.4f}'.format(accuracy))
    # print('F1 Score:\t{:.4f}'.format(f1))
    # print('AUC Score:\t{:.4f}'.format(auc_score))
    #
    # ax[0].plot(fpr, tpr, label='AUC = {:.3f}'.format(auc_score))
    # ax[0].grid()
    # ax[0].legend()
    # ax[0].set_title('ROC Curve')
    #
    # cm = confusion_matrix(y_pred_best, y_true)
    # cm_plot = ax[1].matshow(cm, cmap='Blues_r')
    # ax[1].set_title('Confusion Matrix')
    # ax[1].set_xlabel('True')
    # ax[1].set_ylabel('Predicted')
    # ax[1].xaxis.set_ticks_position('bottom')
    # plt.colorbar(cm_plot)
    # ax[1].set_xticklabels(['No Defects', 'No Defects', 'Defects'])
    # ax[1].set_yticklabels(['No Defects', 'No Defects', 'Defects'])
    # for i in range(n_output):
    #     for j in range(n_output):
    #         k = 0
    #         ax[1].text(j, i, cm[i, j], va='center', ha='center')

if __name__ == '__main__':
    main()
