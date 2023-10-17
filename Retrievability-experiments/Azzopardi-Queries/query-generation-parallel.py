# imports
import pickle
from tqdm import tqdm
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
import multiprocessing
import itertools
import os

# nltk imports
import nltk
from nltk.corpus import stopwords
from nltk.tokenize import word_tokenize
from nltk.util import ngrams

# lucene imports
import lucene
from org.apache.lucene.search import IndexSearcher
from org.apache.lucene.index import DirectoryReader
from org.apache.lucene.store import FSDirectory, SimpleFSDirectory
from java.io import File


# start lucene virtual machine
lucene.initVM()


# This class returns a corpus document field content generator (as an iterator)
class MyCorpus:
    def __init__(self, indexPath, fieldname):
        # Corpus documents directory path
        directory = FSDirectory.open(File(indexPath).toPath())
        self.indexReader = DirectoryReader.open(directory)
        self.numDocs = self.indexReader.numDocs()   # no. docs in English Wikipedia or its index
        self.FIELDNAME = fieldname
    
    def __iter__(self):
        
        for luceneDocid in range(self.numDocs):
            yield luceneDocid, self.indexReader.document(luceneDocid).get(self.FIELDNAME)


def process_one_document(doc):
    # text pre-processing:
    # word tokenization
    doc_tokens = word_tokenize(doc)
    # stopword removal and only alphabetical filtering
    en_stopwords = set(stopwords.words('english'))
    doc_tokens = [w for w in doc_tokens if w.isalpha() and (not w.lower() in en_stopwords)]

    # to store ngrams of the given doc with their frequencies
    doc_unigram_counter = Counter()
    doc_bigram_counter = Counter()

    unigrams = ngrams(doc_tokens, 1)
    bigrams = ngrams(doc_tokens, 2)
    
    unigrams = [ele[0].lower() for ele in unigrams]
    bigrams = [' '.join(ele).lower() for ele in bigrams]
    
    # Add to doc ngrams Counters
    doc_unigram_counter.update(unigrams)
    doc_bigram_counter.update(bigrams)
        
    return doc_unigram_counter, doc_bigram_counter


def process_documents(docs):
    # list of counters for this batch of documents
    batch_unigram_counter = Counter()
    batch_bigram_counter = Counter()
    
    for luceneDocid, doc in docs:
        doc_unigram_counter, doc_bigram_counter = process_one_document(doc)
        
        # adding into batch counters
        batch_unigram_counter += doc_unigram_counter
        batch_bigram_counter += doc_bigram_counter
    
    return batch_unigram_counter, batch_bigram_counter


def parallel_process_documents(corpus, num_workers, batch_size, numDocs):
    # ngrams and their frequencies for all corpus docs
    total_unigram_counter = Counter()
    total_bigram_counter = Counter()
    
    # numDocs = corpus.numDocs
    
    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        tasks = {}
        corpus_iter = iter(corpus)

        # Submit initial tasks
        num_tasks = min(num_workers, numDocs // batch_size + 1)
        for i in range(num_tasks):
            # start_docid = main_start_docid + i*batch_size
            # end_docid = min(start_docid + batch_size, numDocs)
            docs = list(itertools.islice(corpus_iter, batch_size))
            start_docid = docs[0][0]
            end_docid = docs[-1][0]
            future = executor.submit(process_documents, docs)
            tasks[future] = (start_docid, end_docid)

        with tqdm(total=numDocs) as progress_bar:
            while tasks:
                done, _ = wait(tasks, return_when=FIRST_COMPLETED)
                for future in done:
                    batch_unigram_counter, batch_bigram_counter = future.result()

                    # Add the queries counters from this single doc to the global counter
                    total_unigram_counter += batch_unigram_counter
                    total_bigram_counter += batch_bigram_counter

                    del tasks[future]
                    progress_bar.update(batch_size)
                    
                    # Submit a new task
                    # start_docid = max_end_docid_in_tasks
                    # end_docid = min(start_docid + batch_size, numDocs)
                    docs = list(itertools.islice(corpus_iter, batch_size))
                    if len(docs) > 0:
                        start_docid = docs[0][0]
                        end_docid = docs[-1][0]
                        future = executor.submit(process_documents, docs)
                        tasks[future] = (start_docid, end_docid)

    return total_unigram_counter, total_bigram_counter


def main():
    corpus = 'MSMARCO'
    FIELDNAME = 'CONTENT'       # Lucene index field name for content of the doc
    index_path = '../../../../../store/collection/indexed/msmarco-passage'   # Lucene index directory path

    # enwiki doc generator object
    wt10g_corpus = MyCorpus(index_path, FIELDNAME)
    numDocs = wt10g_corpus.numDocs
    
    # specify batch_size for no. of docs to each worker thread
    batch_size = 1000

    num_workers = multiprocessing.cpu_count()-1     # You can adjust this based on your machine's capabilities
    unigram_counter, bigram_counter = parallel_process_documents(wt10g_corpus, num_workers, batch_size=batch_size, numDocs=numDocs)
    
    # dump the total counters for each ngrams for further processing and filtering
    output_dir = corpus
    directory_name = 'counters-dumps'
    directory_path = os.path.join(output_dir, directory_name)
    os.makedirs(directory_path, exist_ok=True)
    with open(os.path.join(directory_path, 'unigram_counter.pickle'), 'wb') as f:
        pickle.dump(unigram_counter, f)
    with open(os.path.join(directory_path, 'bigram_counter.pickle'), 'wb') as f:
        pickle.dump(bigram_counter, f)


if __name__=='__main__':
    main()