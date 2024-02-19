import torch
from torch.utils.data import Dataset, TensorDataset, DataLoader
from PIL import Image
import os, random, sys
import util
from tqdm import tqdm

def convert_to_bert_ids(seq, tokenizer, max_seq_len):
    tokens = tokenizer.tokenize(seq)
    if len(tokens) > max_seq_len - 2:
        tokens = tokens[0:(max_seq_len-2)]
    # length = len(tokens)
    tokens.insert(0, '[CLS]')
    tokens.append('[SEP]')
    ids = tokenizer.convert_tokens_to_ids(tokens)
    padded_ids = [0] * max_seq_len
    padded_ids[:len(ids)] = ids
    mask = [0] * max_seq_len
    mask[:len(ids)] = [1] * len(ids)

    # assert len(padded_ids) == max_seq_len
    # assert len(mask) == max_seq_len

    padded_ids = torch.tensor(padded_ids, dtype=torch.long)
    mask = torch.tensor(mask, dtype=torch.long)

    return padded_ids, mask

def convert_to_bert_ids_no_sep(seq, tokenizer, max_seq_len):
    tokens = tokenizer.tokenize(seq)
    if len(tokens) > max_seq_len - 2:
        tokens = tokens[0:(max_seq_len-2)]
    tokens.insert(0, '[CLS]')
    length = len(tokens)
    ids = tokenizer.convert_tokens_to_ids(tokens)
    padded_ids = [0] * max_seq_len
    padded_ids[:len(ids)] = ids
    mask = [0] * max_seq_len
    mask[:len(ids)] = [1] * len(ids)

    # assert len(padded_ids) == max_seq_len
    # assert len(mask) == max_seq_len

    padded_ids = torch.tensor(padded_ids, dtype=torch.long)
    mask = torch.tensor(mask, dtype=torch.long)

    return padded_ids, mask, length

class PoemImageDataset(Dataset):
    def __init__(self, data, img_dir, word2idx, transform = None, train=True):
        num_train = int(len(data) * 0.95)
        self.img_dir = img_dir
        self.transform = transform
        self.word2idx = word2idx
        if train:
            self.data = data[:num_train]
        else:
            self.data = data[num_train:]

    def __len__(self):
        return len(self.data)

    def __getitem__(self, index):
        '''
        :param index:
        :return:
            img: [ , 224, 224, 3] tensor
            word_ind: [ , T] word indices tensor
        '''

        d = self.data[index]
        poem = d['poem'].replace('\n', ' \n ').split(' ')
        word_ind = [self.word2idx[word] for word in poem]
        word_ind = torch.tensor(word_ind, dtype=torch.int64)
        img = Image.open(os.path.join(self.img_dir, '{}.jpg'.format(d['id']))).convert('RGB')
        img = self.transform(img)

        return img, word_ind

def aligned_ids(seq, basic_tokenizer, tokenizer, word2idx, max_seq_len):
    seq = seq.replace('\n', ' ; ')
    tokens = tokenizer.tokenize(seq)
    if len(tokens) > max_seq_len - 2:
        tokens = tokens[0:(max_seq_len-2)]

    tokens.insert(0, '[CLS]')
    tokens.append('[SEP]')
    ids = tokenizer.convert_tokens_to_ids(tokens)
    padded_ids = [0] * max_seq_len
    padded_ids[:len(ids)] = ids
    attention_mask = [0] * max_seq_len
    attention_mask[:len(ids)] = [1] * len(ids)

    padded_ids = torch.tensor(padded_ids, dtype=torch.long)
    attention_mask = torch.tensor(attention_mask, dtype=torch.long)

    basic_tokens = basic_tokenizer.tokenize(seq)
    # basic_tokens = seq.split()
    # basic_tokens.insert(0, '[CLS]')
    align_mask = [0] * max_seq_len

    word_ind = [0] * max_seq_len
    i = 0
    for j, token in enumerate(tokens):
        if token.startswith('##'):
            continue
        else:
            if token=='[SEP]':
                word_ind[i] = (word2idx['[SEP]'])
                i += 1
                # align_mask[j] = 1
                break
            if token == '[CLS]':
                align_mask[j] = 1
                continue
            if not basic_tokens[i].startswith(token):
                print(basic_tokens, tokens, basic_tokens[i], token)
            assert basic_tokens[i].startswith(token)
            if basic_tokens[i] not in word2idx:
                i += 1
                continue
            word_ind[i] = word2idx[basic_tokens[i]]
            align_mask[j] = 1
            i += 1
    length_m1 = torch.tensor(i-1, dtype=torch.long)
    align_mask = torch.tensor(align_mask, dtype=torch.long)
    word_ind = torch.tensor(word_ind, dtype=torch.long)

    return padded_ids, attention_mask, align_mask, word_ind, length_m1



def build_unim_dataset(data, features, basic_tokenizer, tokenizer, word2idx, max_seq_len=256):
    id_list = []
    attn_mask_list = []
    align_mask_list = []
    word_ind_list = []
    length_m1_list = []
    feature_list = []
    dataloader = []
    sys.stderr.write('Building dataset...\n')
    for entry in tqdm(data):
        if entry['id'] == 28886:
            continue
        id, attn_mask, align_mask, word_ind, length_m1 = aligned_ids(
            entry['poem'], basic_tokenizer, tokenizer, word2idx, max_seq_len)
        feature = features[entry['id']]
        feature_list.append(feature)
        id_list.append(id)
        attn_mask_list.append(attn_mask)
        align_mask_list.append(align_mask)
        word_ind_list.append(word_ind)
        length_m1_list.append(length_m1)
        # dataloader.append((id, attn_mask, align_mask, word_ind))
    ids = torch.stack(id_list, 0)
    attn_masks = torch.stack(attn_mask_list, 0)
    align_masks = torch.stack(align_mask_list, 0)
    word_inds = torch.stack(word_ind_list, 0)
    lengths_m1 = torch.stack(length_m1_list, 0)
    feature_tensors = torch.tensor(feature_list)
    dataset = TensorDataset(ids, attn_masks, align_masks, word_inds, lengths_m1, feature_tensors)

    return dataset

class UnimDataset(Dataset):
    def __init__(self, data, features, basic_tokenizer, tokenizer, word2idx, max_seq_len):
        super(UnimDataset, self).__init__()
        self.data = data
        self.features = features
        self.basic_tokenizer = basic_tokenizer
        self.tokenizer = tokenizer
        self.word2idx = word2idx
        self.max_seq_len = max_seq_len

    def __len__(self):
        return len(self.data)

    def __getitem__(self, index):
        entry = self.data[index]
        if entry['id'] == 28886:
            return self.__getitem__(random.randrange(len(self.data)))
        feature = self.features[entry['id']]
        id, attn_mask, align_mask, word_ind, length_m1 = aligned_ids(
            entry['poem'], self.basic_tokenizer, self.tokenizer, self.word2idx, self.max_seq_len)
        return id, attn_mask, align_mask, word_ind, length_m1, feature


class PoemImageEmbedDataset(Dataset):
    def __init__(self, data, img_dir, tokenizer, max_seq_len, transform = None):
        super(PoemImageEmbedDataset, self).__init__()
        self.img_dir = img_dir
        self.transform = transform
        self.data = data
        self.tokenizer = tokenizer
        self.max_seq_len = max_seq_len

    def __len__(self):
        return len(self.data)

    def __getitem__(self, index):
        sample1 = self.data[index]
        sample2_idx = random.randrange(len(self.data))
        while sample2_idx == index:
            sample2_idx = random.randrange(len(self.data))
        sample2 = self.data[sample2_idx]

        img1 = Image.open(os.path.join(self.img_dir, '{}.jpg'.format(sample1['id']))).convert('RGB')
        img1 = self.transform(img1)
        img2 = Image.open(os.path.join(self.img_dir, '{}.jpg'.format(sample2['id']))).convert('RGB')
        img2 = self.transform(img2)

        ids1, mask1 = convert_to_bert_ids(sample1['poem'], self.tokenizer, self.max_seq_len)
        ids2, mask2 = convert_to_bert_ids(sample2['poem'], self.tokenizer, self.max_seq_len)


        return img1, ids1, mask1, img2, ids2, mask2


class VisualSentimentDataset(Dataset):
    def __init__(self, df, img_dir, transform=None):
        super(VisualSentimentDataset, self).__init__()
        self.df = df
        self.img_dir = img_dir
        self.transform = transform

    def __len__(self):
        return len(self.df)

    def __getitem__(self, index):
        entry = self.df.iloc[index]
        id = entry['id']
        img = Image.open(os.path.join(self.img_dir, '{}.jpg'.format(id))).convert('RGB')
        img = self.transform(img)

        level = {'Highly negative': 0, 'Negative': 0, 'Neutral': 1, 'Positive': 2, 'Highly positive': 2}
        label = level[entry['label']]
        label = torch.tensor(label, dtype=torch.long)

        # label_map = {'negative': 0, 'neutral': 1, 'positive': 2}
        # positive_emotions = ['amusement', 'awe', 'excitement', 'contentment']
        # negative_emotions = ['anger', 'disgust', 'fear', 'sadness']

        # if entry['disagrees'] > entry['agrees']:
        #         label = label_map['neutral']
        # else:
        #     if entry['emotion'] in positive_emotions:
        #         label = label_map['positive']
        #     elif entry['emotion'] in negative_emotions:
        #         label = label_map['negative']
        #     else:
        #         print('Error: unknown emotion {}'.format(entry['emotion']))
        #         exit(-1)
        # label = torch.tensor(label, dtype=torch.long)

        return img, label


class PoemPoemDataset(Dataset):
    def __init__(self, json_obj, features, tokenizer, max_seq_len, word2idx):
        self.json_obj = json_obj
        self.features = features
        self.tokenizer = tokenizer
        self.max_seq_len = max_seq_len
        self.word2idx = word2idx

    def __len__(self):
        return len(self.json_obj)

    def __getitem__(self, item):
        entry = self.json_obj[item]

        # prepare for poem embedder
        # ids, mask = convert_to_bert_ids(entry['poem'], self.tokenizer, self.max_seq_len)
        feature = torch.tensor(self.features[entry['id']])
        # prepare for rnn
        tokens = util.process_one_poem(entry['poem'])
        if len(tokens) > self.max_seq_len - 2:
            tokens = tokens[:self.max_seq_len - 2]

        word_indices = [self.word2idx['<SOS>']] + \
                       [self.word2idx[word] if word in self.word2idx else self.word2idx['<UNK>'] for word in tokens ] + \
                       [self.word2idx['<EOS>']]
        word_indices = torch.tensor(word_indices, dtype=torch.int64)

        return feature, word_indices



def get_poem_poem_dataset(batch_size, shuffle, num_workers, json_obj, features, tokenizer, max_seq_len, word2idx):

    def poem_poem_collate_fn(data):
        """Creates mini-batch tensors from the list of tuples (ids, mask, word_indices).

        We should build custom collate_fn rather than using default collate_fn,
        because merging caption (including padding) is not supported in default.

        Args:
            data: list of tuple (ids, mask, word_indices).
                @ids: used in embedding
                @mask: used in embedding
                @word_indices: word indices with shape (num_words)

        Returns:
            @ids: (batch_size, ...)
            @mask： (batch_size, ...)
            targets: torch tensor of shape (batch_size, padded_length).
            lengths: list; valid length for each padded poem.
        """
        # Sort a data list by caption length (descending order).
        data.sort(key=lambda x: len(x[1]), reverse=True)
        features, word_indices_list = zip(*data)

        # Merge images (from tuple of 3D tensor to 4D tensor).
        # ids = torch.stack(ids, 0)
        # mask = torch.stack(mask, 0)
        features = torch.stack(features, 0)

        # Merge captions (from tuple of 1D tensor to 2D tensor).
        lengths = torch.tensor([len(word_indices) - 1 for word_indices in word_indices_list]).long()
        targets = torch.zeros(len(word_indices_list), max(lengths) + 1).long()
        for i, word_indices in enumerate(word_indices_list):
            end = len(word_indices)
            targets[i, :end] = word_indices
        return features, targets, lengths

    poem_poem_dataset = PoemPoemDataset(json_obj, features, tokenizer, max_seq_len, word2idx)
    data_loader = torch.utils.data.DataLoader(
        dataset=poem_poem_dataset,
        batch_size=batch_size,
        shuffle=shuffle,
        num_workers=num_workers,
        collate_fn=poem_poem_collate_fn,
    )
    return data_loader
