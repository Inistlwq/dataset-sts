"""
KeraSTS interface for the Ubuntu dataset of the Answer Sentence Selection
(Next Utterance Ranking) task.

Training example:
    tools/train.py avg ubuntu data/anssel/ubuntu/v2-trainset.pickle data/anssel/ubuntu/v2-valset.pickle "vocabf='data/anssel/ubuntu/v2-vocab.pickle'"

If this crashes due to out-of-memory error, you'll need to lower the batch
size - pass e.g. batch_size=128.  To speed up training, you may want to
conversely bump the batch_size if you have a smaller model (e.g. cnn).

First, you must however run:
    tools/ubuntu_preprocess.py --revocab data/anssel/ubuntu/v2-trainset.csv data/anssel/ubuntu/v2-trainset.pickle data/anssel/ubuntu/v2-vocab.pickle
    tools/ubuntu_preprocess.py data/anssel/ubuntu/v2-valset.csv data/anssel/ubuntu/v2-valset.pickle data/anssel/ubuntu/v2-vocab.pickle
    tools/ubuntu_preprocess.py data/anssel/ubuntu/v2-testset.csv data/anssel/ubuntu/v2-testset.pickle data/anssel/ubuntu/v2-vocab.pickle
(N.B. this will include only the first 1M samples of the train set).

(TODO: Make these downloadable.)

Notes:
    * differs from https://github.com/npow/ubottu/blob/master/src/merge_data.py
      in that all unseen words outside of train set share a single
      common random vector rather than each having a different one
      (or deferring to stock GloVe vector)
    * reduced vocabulary only to words that appear at least twice,
      because the embedding matrix is too big for our GPUs otherwise
    * in case of too long sequences, the beginning is discarded rather
      than the end; this is different from KeraSTS default as well as
      probably the prior art

Ideas (future work):
    * rebuild the train set to train for a ranking task rather than
      just identification task?
"""

from __future__ import print_function
from __future__ import division

from keras.preprocessing.sequence import pad_sequences
import numpy as np
try:
    import cPickle
except ImportError:  # python3
    import pickle as cPickle
import pickle
import random

import pysts.eval as ev
from pysts.kerasts import graph_input_anssel, graph_input_slice
import pysts.nlp as nlp

from .anssel import AnsSelTask


def pad_3d_sequence(seqs, maxlen, nd, dtype='int32'):
    pseqs = np.zeros((len(seqs), maxlen, nd)).astype(dtype)
    for i, seq in enumerate(seqs):
        trunc = np.array(seq[-maxlen:], dtype=dtype)  # trunacting='pre'
        pseqs[i, :trunc.shape[0]] = trunc  # padding='post'
    return pseqs


def pad_graph(gr, s0pad, s1pad):
    """ pad sequences in the graph """
    gr['si0'] = pad_sequences(gr['si0'], maxlen=s0pad, truncating='pre', padding='post')
    gr['si1'] = pad_sequences(gr['si1'], maxlen=s1pad, truncating='pre', padding='post')
    gr['f0'] = pad_3d_sequence(gr['f0'], maxlen=s0pad, nd=nlp.flagsdim)
    gr['f1'] = pad_3d_sequence(gr['f1'], maxlen=s1pad, nd=nlp.flagsdim)
    gr['score'] = np.array(gr['score'])


def sample_pairs(gr, batch_size, s0pad, s1pad, once=False):
    """ A generator that produces random pairs from the dataset """
    # XXX: We drop the last few samples if (1e6 % batch_size != 0)
    # XXX: We never swap samples between batches, does it matter?
    ids = range(int(len(gr['si0']) / batch_size))
    while True:
        random.shuffle(ids)
        for i in ids:
            sl = slice(i * batch_size, (i+1) * batch_size)
            ogr = graph_input_slice(gr, sl)
            # TODO: Add support for discarding too long samples?
            pad_graph(ogr, s0pad=s0pad, s1pad=s1pad)
            yield ogr
        if once:
            break


class UbuntuTask(AnsSelTask):
    def __init__(self):
        self.name = 'ubuntu'
        self.s0pad = 160
        self.s1pad = 160
        self.emb = None
        self.vocab = None

    def config(self, c):
        c['loss'] = 'binary_crossentropy'
        c['nb_epoch'] = 16
        c['batch_size'] = 192
        c['epoch_fract'] = 1/4

    def load_set(self, fname, cache_dir=None):
        si0, si1, f0, f1, labels = cPickle.load(open(fname, "rb"))
        gr = graph_input_anssel(si0, si1, labels, f0, f1)
        return (gr, labels, self.vocab)

    def load_vocab(self, vocabf):
        # use plain pickle because unicode
        self.vocab = pickle.load(open(vocabf, "rb"))
        return self.vocab

    def fit_model(self, model, **kwargs):
        batch_size = kwargs.pop('batch_size')
        return model.fit_generator(sample_pairs(self.gr, batch_size, self.s0pad, self.s1pad), **kwargs)

    def eval(self, model):
        res = []
        for gr, fname in [(self.gr, self.trainf), (self.grv, self.valf), (self.grt, self.testf)]:
            if gr is None:
                res.append(None)
                continue
            ypred = model.predict(gr)['score'][:,0]
            res.append(ev.eval_ubuntu(ypred, gr['s0'], gr['score'], fname))
        return tuple(res)

    def res_columns(self, mres, pfx=' '):
        """ Produce README-format markdown table row piece summarizing
        important statistics """
        return('%c%.6f   |%c%.6f     |%c%.6f   |%c%.6f   |%c%.6f    |%c%.6f  |%c%.6f   '
               % (pfx, mres[self.trainf]['MRR'],
                  pfx, mres[self.trainf]['2R_1'],
                  pfx, mres[self.valf]['MRR'],
                  pfx, mres[self.valf]['R2_1'],
                  pfx, mres[self.valf]['R10_2'],
                  pfx, mres[self.testf].get('MAP', np.nan),
                  pfx, mres[self.testf].get('R2_1', np.nan),
                  pfx, mres[self.testf].get('R10_2', np.nan)))


def task():
    return UbuntuTask()
