import torch.nn as nn
import torch

from config import get_params
from preprocess import preprocess

from cezo_fl.server import CeZO_Server
from cezo_fl.client import Client

from models.cnn_mnist import CNN_MNIST
from models.lenet import LeNet
from models.cnn_fashion import CNN_FMNIST
from models.lstm import CharLSTM
from tqdm import tqdm
from gradient_estimators.random_gradient_estimator import RandomGradientEstimator as RGE


def prepare_settings_underseed(args, device):
    torch.manual_seed(args.seed)
    if args.dataset == "mnist":
        model = CNN_MNIST().to(device)
        criterion = nn.CrossEntropyLoss()
        optimizer = torch.optim.SGD(
            model.parameters(), lr=args.lr, weight_decay=1e-5, momentum=args.momentum
        )
        # scheduler = torch.optim.lr_scheduler.ExponentialLR(optimizer, gamma=0.8)
    elif args.dataset == "cifar10":
        model = LeNet().to(device)
        criterion = nn.CrossEntropyLoss()
        optimizer = torch.optim.SGD(
            model.parameters(), lr=args.lr, weight_decay=5e-4, momentum=args.momentum
        )
        # scheduler = torch.optim.lr_scheduler.MultiStepLR(
        #     optimizer, milestones=[200], gamma=0.1
        # )
    elif args.dataset == "fashion":
        model = CNN_FMNIST().to(device)
        criterion = nn.CrossEntropyLoss()
        optimizer = torch.optim.SGD(
            model.parameters(), lr=args.lr, weight_decay=1e-5, momentum=args.momentum
        )
        # scheduler = torch.optim.lr_scheduler.MultiStepLR(
        #     optimizer, milestones=[200], gamma=0.1
        # )
    elif args.dataset == "shakespeare":
        model = CharLSTM().to(device)
        criterion = nn.CrossEntropyLoss()
        optimizer = torch.optim.SGD(
            model.parameters(), lr=args.lr, momentum=0.9, weight_decay=5e-4
        )
        # scheduler = torch.optim.lr_scheduler.MultiStepLR(
        #     optimizer, milestones=[200], gamma=0.1
        # )

    if args.grad_estimate_method in ["rge-central", "rge-forward"]:
        method = args.grad_estimate_method[4:]
        print(f"Using RGE {method}")
        grad_estimator = RGE(
            model,
            mu=args.mu,
            num_pert=args.num_pert,
            grad_estimate_method=method,
            device=device,
        )
    else:
        raise Exception(
            f"Grad estimate method {args.grad_estimate_method} not supported"
        )
    return model, criterion, optimizer, grad_estimator


# def get_warmup_lr(
#     args, current_epoch: int, current_iter: int, iters_per_epoch: int
# ) -> float:
#     overall_iterations = args.warmup_epochs * iters_per_epoch + 1
#     current_iterations = current_epoch * iters_per_epoch + current_iter + 1
#     return args.lr * current_iterations / overall_iterations


if __name__ == "__main__":
    args = get_params().parse_args()

    clients = []

    for i in range(args.num_clients):
        device, train_loader, _ = preprocess(args)
        client_model, client_criterion, client_optimizer, client_grad_estimator = (
            prepare_settings_underseed(args, device)
        )
        client_model.to(device)

        client = Client(
            client_model,
            train_loader,
            client_grad_estimator,
            client_optimizer,
            client_criterion,
            device,
        )
        clients.append(client)

    server = CeZO_Server(clients, device, num_sample_clients=3, local_update_steps=5)

    # set server tools
    device, _, test_loader = preprocess(args)
    server_model, server_criterion, server_optimizer, server_grad_estimator = (
        prepare_settings_underseed(args, device)
    )
    server_model.to(device)
    server.set_server_model_and_criterion(
        server_model, server_criterion, server_optimizer, server_grad_estimator
    )

    with tqdm(total=args.iterations, desc="Training:") as t, torch.no_grad():
        for ite in range(args.iterations):
            server.train_one_step(ite)
            t.update(1)

            # eval loss
            if (ite + 1) % 20 == 0:
                eval_loss, eval_accuracy = server.eval_model(test_loader)
                t.set_postfix({"Loss": eval_loss, "Accuracy": eval_loss})