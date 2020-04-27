from __future__ import absolute_import, division, print_function

import logging
import logging.handlers
import math
import pickle
import random
import sys

import numpy as np
import scipy.sparse as sp
import torch
from collections import defaultdict
from sklearn.feature_extraction.text import TfidfTransformer

# Dataset names.
BEAUTY = 'beauty'
CELL = 'cell'
CLOTH = 'cloth'
CD = 'cd'

# Dataset directories.
DATASET_DIR = {
    BEAUTY: './data/Amazon_Beauty',
    CELL: './data/Amazon_Cellphones',
    CLOTH: './data/Amazon_Clothing',
    CD: './data/Amazon_CDs',
}

# Model result directories.
TMP_DIR = {
    BEAUTY: './tmp/Amazon_Beauty',
    CELL: './tmp/Amazon_Cellphones',
    CLOTH: './tmp/Amazon_Clothing',
    CD: './tmp/Amazon_CDs',
}

# Label files.
LABELS = {
    BEAUTY: (TMP_DIR[BEAUTY] + '/train_label.pkl', TMP_DIR[BEAUTY] + '/test_label.pkl'),
    CLOTH: (TMP_DIR[CLOTH] + '/train_label.pkl', TMP_DIR[CLOTH] + '/test_label.pkl'),
    CELL: (TMP_DIR[CELL] + '/train_label.pkl', TMP_DIR[CELL] + '/test_label.pkl'),
    CD: (TMP_DIR[CD] + '/train_label.pkl', TMP_DIR[CD] + '/test_label.pkl')
}

# Brand Popularity files.
BRAND_FILE = {
    BEAUTY: './brand_data/pid_fairness_beauty.pickle',
    CELL: './brand_data/pid_fairness_cell.pickle',
    CLOTH: './brand_data/brand_cloth_2014.pickle',
    CD: './brand_data/pid_fairness_cd.pickle',
}

# Entities
USER = 'user'
PRODUCT = 'product'
WORD = 'word'
RPRODUCT = 'related_product'
BRAND = 'brand'
CATEGORY = 'category'


# Relations
PURCHASE = 'purchase'
MENTION = 'mentions'
DESCRIBED_AS = 'described_as'
PRODUCED_BY = 'produced_by'
BELONG_TO = 'belongs_to'
ALSO_BOUGHT = 'also_bought'
ALSO_VIEWED = 'also_viewed'
BOUGHT_TOGETHER = 'bought_together'
SELF_LOOP = 'self_loop'  # only for kg env

KG_RELATION = {
    USER: {
        PURCHASE: PRODUCT,
        MENTION: WORD,
    },
    WORD: {
        MENTION: USER,
        DESCRIBED_AS: PRODUCT,
    },
    PRODUCT: {
        PURCHASE: USER,
        DESCRIBED_AS: WORD,
        PRODUCED_BY: BRAND,
        BELONG_TO: CATEGORY,
        ALSO_BOUGHT: RPRODUCT,
        ALSO_VIEWED: RPRODUCT,
        BOUGHT_TOGETHER: RPRODUCT,
    },
    BRAND: {
        PRODUCED_BY: PRODUCT,
    },
    CATEGORY: {
        BELONG_TO: PRODUCT,
    },
    RPRODUCT: {
        ALSO_BOUGHT: PRODUCT,
        ALSO_VIEWED: PRODUCT,
        BOUGHT_TOGETHER: PRODUCT,
    }
}


PATH_PATTERN = {
    # length = 3
    #############
    # Paths starting with the User
    1: ((None, USER), (MENTION, WORD), (DESCRIBED_AS, PRODUCT)),
    # Paths starting with the Product
    2: ((None, PRODUCT), (DESCRIBED_AS, WORD), (MENTION, USER)),

    # length = 4
    #############
    # Paths starting with the User
    11: ((None, USER), (PURCHASE, PRODUCT), (PURCHASE, USER), (PURCHASE, PRODUCT)),
    12: ((None, USER), (PURCHASE, PRODUCT), (DESCRIBED_AS, WORD), (DESCRIBED_AS, PRODUCT)),
    13: ((None, USER), (PURCHASE, PRODUCT), (PRODUCED_BY, BRAND), (PRODUCED_BY, PRODUCT)),
    14: ((None, USER), (PURCHASE, PRODUCT), (BELONG_TO, CATEGORY), (BELONG_TO, PRODUCT)),
    15: ((None, USER), (PURCHASE, PRODUCT), (ALSO_BOUGHT, RPRODUCT), (ALSO_BOUGHT, PRODUCT)),
    16: ((None, USER), (PURCHASE, PRODUCT), (ALSO_VIEWED, RPRODUCT), (ALSO_VIEWED, PRODUCT)),
    17: ((None, USER), (PURCHASE, PRODUCT), (BOUGHT_TOGETHER, RPRODUCT), (BOUGHT_TOGETHER, PRODUCT)),
    18: ((None, USER), (MENTION, WORD), (MENTION, USER), (PURCHASE, PRODUCT)),
    # Paths starting with the Product
    21: ((None, PRODUCT), (PURCHASE, USER), (PURCHASE, PRODUCT), (PURCHASE, USER)),
    22: ((None, PRODUCT), (DESCRIBED_AS, WORD), (DESCRIBED_AS, PRODUCT), (PURCHASE, USER)),
    23: ((None, PRODUCT), (PRODUCED_BY, BRAND), (PRODUCED_BY, PRODUCT), (PURCHASE, USER)),
    24: ((None, PRODUCT), (BELONG_TO, CATEGORY), (BELONG_TO, PRODUCT), (PURCHASE, USER)),
    25: ((None, PRODUCT), (ALSO_BOUGHT, RPRODUCT), (ALSO_BOUGHT, PRODUCT), (PURCHASE, USER)),
    26: ((None, PRODUCT), (ALSO_VIEWED, RPRODUCT), (ALSO_VIEWED, PRODUCT), (PURCHASE, USER)),
    27: ((None, PRODUCT), (BOUGHT_TOGETHER, RPRODUCT), (BOUGHT_TOGETHER, PRODUCT), (PURCHASE, USER)),
    28: ((None, PRODUCT), (PURCHASE, USER), (MENTION, WORD), (MENTION, USER)),
}


def get_entities():
    return list(KG_RELATION.keys())


def get_relations(entity_head):
    return list(KG_RELATION[entity_head].keys())


def get_entity_tail(entity_head, relation):
    return KG_RELATION[entity_head][relation]


def compute_tfidf_fast(vocab, docs):
    """Compute TFIDF scores for all vocabs.

    Args:
        docs: list of list of integers, e.g. [[0,0,1], [1,2,0,1]]

    Returns:
        sp.csr_matrix, [num_docs, num_vocab]
    """
    # (1) Compute term frequency in each doc.
    data, indices, indptr = [], [], [0]
    for d in docs:
        term_count = {}
        for term_idx in d:
            if term_idx not in term_count:
                term_count[term_idx] = 1
            else:
                term_count[term_idx] += 1
        indices.extend(term_count.keys())
        data.extend(term_count.values())
        indptr.append(len(indices))
    tf = sp.csr_matrix((data, indices, indptr), dtype=int, shape=(len(docs), len(vocab)))

    # (2) Compute normalized tfidf for each term/doc.
    transformer = TfidfTransformer(smooth_idf=True)
    tfidf = transformer.fit_transform(tf)
    return tfidf


def get_logger(logname):
    logger = logging.getLogger(logname)
    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter('[%(levelname)s]  %(message)s')
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    fh = logging.handlers.RotatingFileHandler(logname, mode='w')
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    return logger


def set_random_seed(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def save_dataset(dataset, dataset_obj):
    dataset_file = TMP_DIR[dataset] + '/dataset.pkl'
    with open(dataset_file, 'wb') as f:
        pickle.dump(dataset_obj, f)


def load_dataset(dataset):
    dataset_file = TMP_DIR[dataset] + '/dataset.pkl'
    dataset_obj = pickle.load(open(dataset_file, 'rb'))
    return dataset_obj


def save_labels(dataset, labels, mode='train'):
    if mode == 'train':
        label_file = LABELS[dataset][0]
    elif mode == 'test':
        label_file = LABELS[dataset][1]
    else:
        raise Exception('mode should be one of {train, test}.')
    with open(label_file, 'wb') as f:
        pickle.dump(labels, f)


def load_labels(dataset, mode='train'):
    if mode == 'train':
        label_file = LABELS[dataset][0]
    elif mode == 'test':
        label_file = LABELS[dataset][1]
    else:
        raise Exception('mode should be one of {train, test}.')
    user_products = pickle.load(open(label_file, 'rb'))
    return user_products


def save_embed(dataset, embed):
    embed_file = '{}/transe_embed.pkl'.format(TMP_DIR[dataset])
    pickle.dump(embed, open(embed_file, 'wb'))


def load_embed(dataset):
    embed_file = '{}/transe_embed.pkl'.format(TMP_DIR[dataset])
    print('Load embedding:', embed_file)
    embed = pickle.load(open(embed_file, 'rb'))
    return embed


def save_kg(dataset, kg):
    kg_file = TMP_DIR[dataset] + '/kg.pkl'
    pickle.dump(kg, open(kg_file, 'wb'))


def load_kg(dataset):
    kg_file = TMP_DIR[dataset] + '/kg.pkl'
    kg = pickle.load(open(kg_file, 'rb'))
    return kg


def invert_labels(labels):
    """
    Inverts a mapping of user:[products] to product:[users] and vice versa
    :param labels: dictionary of user:[products] (or vice versa)
    :return: inverted dictionary of product:[users] (or vice versa)
    """
    inv_labels = defaultdict(set)
    for k, vs in labels.items():
        for v in vs:
            inv_labels[v].add(k)
    return inv_labels


def represents_int(s):
    try:
        int(s)
        return True
    except ValueError:
        return False


def calculate_fairness(item_predictions, fairness_dict):
    fairness_score = 0
    num_items = 0
    for pid in item_predictions:
        if pid in fairness_dict:
            if fairness_dict[pid] > 10:  # there are some corrupt values
                continue
            fairness_score += math.sqrt(fairness_dict[pid])
            num_items += 1

    if num_items == 0:
        return 0

    denominator = float(num_items - math.sqrt(num_items))

    if denominator <= 0:
        denominator = 1

    fairness_score = float(fairness_score - math.sqrt(num_items)) / denominator

    return fairness_score
