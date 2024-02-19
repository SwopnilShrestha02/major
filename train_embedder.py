import torch
import torchvision.models as models
import torch.nn as nn
from torch.nn import DataParallel
import torchvision.transforms as transforms
import torch.optim as optim
from torch.utils.data import DataLoader
from pytorch_pretrained_bert import BertTokenizer
import os, sys, time, argparse, logging
from dataloader import PoemImageDataset, PoemImageEmbedDataset
from model import PoemImageEmbedModel
import json
from util import load_vocab_json, build_vocab, check_path, filter_multim
from tqdm import tqdm

logging.basicConfig(format = '%(asctime)s - %(levelname)s - %(name)s -   %(message)s',
                    datefmt = '%m/%d/%Y %H:%M:%S',
                    level = logging.INFO)
logger = logging.getLogger(__name__)

def load_dataparallel(model, load_model):
    state_dict_parallel = torch.load(load_model)
    state_dict = {key[7:]: value for key, value in state_dict_parallel.items()}
    model.load_state_dict(state_dict)

class PoemImageEmbedTrainer():
    def __init__(self, train_data, test_data, sentiment_model, batchsize, load_model, device):
        self.device = device
        self.train_data = train_data
        self.test_data = test_data
        self.tokenizer = BertTokenizer.from_pretrained('bert-base-uncased')

        self.train_transform = transforms.Compose([
            transforms.RandomResizedCrop(224),
            transforms.RandomHorizontalFlip(),
            transforms.ToTensor()
        ])

        self.test_transform = transforms.Compose([
            transforms.Resize((224, 224)),
            transforms.ToTensor()
        ])

        img_dir = 'data/image'
        self.train_set = PoemImageEmbedDataset(self.train_data, img_dir,
                                               tokenizer=self.tokenizer, max_seq_len=100,
                                               transform=self.train_transform)
        self.train_loader = DataLoader(self.train_set, batch_size=batchsize, shuffle=True, num_workers=4)

        self.test_set = PoemImageEmbedDataset(self.test_data, img_dir,
                                              tokenizer=self.tokenizer, max_seq_len=100,
                                              transform=self.test_transform)
        self.test_loader = DataLoader(self.test_set, batch_size=batchsize, num_workers=4)

        self.model = PoemImageEmbedModel(device)

        self.model = DataParallel(self.model)
        load_dataparallel(self.model.module.img_embedder.sentiment_feature, sentiment_model)
        if load_model:
            logger.info('load model from '+ load_model)
            self.model.load_state_dict(torch.load(load_model))
        self.model.to(device)
        self.optimizer = optim.Adam(list(self.model.module.poem_embedder.linear.parameters()) + \
                                    list(self.model.module.img_embedder.linear.parameters()), lr=1e-4)
        self.scheduler = optim.lr_scheduler.MultiStepLR(self.optimizer, milestones=[2, 4, 6], gamma=0.33)

    def train_epoch(self, epoch, log_interval, save_interval, ckpt_file):
        self.model.train()
        running_ls = 0
        acc_ls = 0
        start = time.time()
        num_batches = len(self.train_loader)
        for i, batch in enumerate(self.train_loader):
            img1, ids1, mask1, img2, ids2, mask2 = [t.to(self.device) for t in batch]
            self.model.zero_grad()
            loss = self.model(img1, ids1, mask1, img2, ids2, mask2)
            loss.backward(torch.ones_like(loss))
            running_ls += loss.mean().item()
            acc_ls += loss.mean().item()
            self.optimizer.step()

            if (i + 1) % log_interval == 0:
                elapsed_time = time.time() - start
                iters_per_sec = (i + 1) / elapsed_time
                remaining = (num_batches - i - 1) / iters_per_sec
                remaining_time = time.strftime("%H:%M:%S", time.gmtime(remaining))

                print('[{:>2}, {:>4}/{}] running loss:{:.4} acc loss:{:.4} {:.3}iters/s {} left'.format(
                    epoch, (i + 1), num_batches, running_ls / log_interval, acc_ls /(i+1),
                    iters_per_sec, remaining_time))
                running_ls = 0

            if (i + 1) % save_interval == 0:
                self.save_model(ckpt_file)

    def save_model(self, file):
        torch.save(self.model.state_dict(), file)


def main():
    argparser = argparse.ArgumentParser()
    argparser.add_argument('--load-model', default=None)
    argparser.add_argument('-e', '--num_epoch', type=int, default=10)
    argparser.add_argument('-t', '--test', default=False, action='store_true')
    argparser.add_argument('--pt', default=False, action='store_true', help='prototype mode')
    argparser.add_argument('-b', '--batchsize', type=int, default=32)
    argparser.add_argument('--log-interval', type=int, default=10)
    argparser.add_argument('--save-interval', type=int, default=100)
    argparser.add_argument('-r', '--restore', default=False, action='store_true',
                           help='restore from checkpoint')
    argparser.add_argument('--ckpt', default='saved_model/embedder_ckpt.pth')
    argparser.add_argument('--save', default='saved_model/embedder.pth')
    args = argparser.parse_args()

    logging.info('reading data')
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    with open('data/multim_poem.json') as f:
        multim = json.load(f)

    multim = filter_multim(multim)

    train_data = multim
    test_data = multim
    logging.info('number of training data:{}, number of testing data:{}'.
                 format(len(train_data), len(test_data)))

    if args.pt:
        train_data = train_data[:1000]
        test_data = test_data[:20]

    logging.info('building model...')
    load_model = args.load_model
    if args.load_model is None and args.restore and os.path.exists(args.ckpt):
        load_model = args.ckpt

    sentiment_model = 'saved_model/sentiment_all.pth'
    embed_trainer = PoemImageEmbedTrainer(train_data, test_data, sentiment_model, args.batchsize, load_model, device)
    check_path('saved_model')
    if args.test:
        pass
    else:
        logging.info('start traning')
        for e in range(args.num_epoch):
            embed_trainer.train_epoch(e+1, args.log_interval, args.save_interval, args.ckpt)
            embed_trainer.save_model(args.ckpt)
        embed_trainer.save_model(args.save)


if __name__ == '__main__':
    main()
