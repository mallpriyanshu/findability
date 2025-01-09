# imports
import pickle
import json
from tqdm import tqdm
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
import multiprocessing
import itertools
import os
import numpy as np
import random
import math

# lucene imports
import lucene
from org.apache.lucene.search import IndexSearcher
from org.apache.lucene.index import DirectoryReader, Term, PostingsEnum, MultiTerms
from org.apache.lucene.store import FSDirectory, SimpleFSDirectory
from org.apache.lucene.util import BytesRefIterator
from java.io import File


# start lucene virtual machine
lucene.initVM()


def documentTermSelectionModel(termVector, indexReader, N, FIELDNAME):
    ''' user's language model of the document '''
    # return popularSelection(termVector)
    return popularPlusDiscriminativeSelection(termVector, indexReader, N, FIELDNAME)
    

def popularPlusDiscriminativeSelection(termVector, indexReader, N, FIELDNAME):
    ''' Popular + Discrimination Selection Scheme '''
    p_t_dk = {}
    terms_enum = termVector
    for term in BytesRefIterator.cast_(terms_enum):
        term_text = term.utf8ToString()
        postings_enum = terms_enum.postings(None)
        while postings_enum.nextDoc() != PostingsEnum.NO_MORE_DOCS:
            freq = postings_enum.freq()
        df = indexReader.docFreq(Term(FIELDNAME, term_text))    # docFreq of term,t
        idf = math.log10(N/(df+1))
        p_t_dk[term_text] = freq*idf
    
    total = sum(p_t_dk.values())
    p_t_dk = {term:weight/total for term,weight in p_t_dk.items()}
    return p_t_dk


def popularSelection(termVector):
    ''' Popular Selection Scheme '''
    term_frequency_vector = {}
    terms_enum = termVector
    for term in BytesRefIterator.cast_(terms_enum):
        term_text = term.utf8ToString()
        postings_enum = terms_enum.postings(None)
        while postings_enum.nextDoc() != PostingsEnum.NO_MORE_DOCS:
            freq = postings_enum.freq()
            term_frequency_vector[term_text] = freq
    
    total = sum(term_frequency_vector.values())
    p_t_dk = {term:tf/total for term,tf in term_frequency_vector.items()}
    return p_t_dk


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
            try:
                term_vector = self.indexReader.getTermVector(luceneDocid, self.FIELDNAME).iterator()
                p_t_dk = documentTermSelectionModel(term_vector, self.indexReader, self.numDocs, self.FIELDNAME)
            except:
                p_t_dk = {}
            yield luceneDocid, p_t_dk


def compute_p_t_dist(indexPath, FIELDNAME):
    # Open the Lucene index directory
    directory = FSDirectory.open(File(indexPath).toPath())
    reader = DirectoryReader.open(directory)

    # p_t distribution
    p_t = {}
    
    # count no. of terms in the vocabulary
    terms = MultiTerms.getTerms(reader, FIELDNAME)
    terms_enum = terms.iterator()
    countTerms = 0
    for term in BytesRefIterator.cast_(terms_enum):
        countTerms += 1
    
    # Get the vocabulary terms
    terms = MultiTerms.getTerms(reader, FIELDNAME)

    # Iterate over the terms and get their collection frequencies
    terms_enum = terms.iterator()
    for term in tqdm(BytesRefIterator.cast_(terms_enum), desc='P(t) computation', total=countTerms):
        term_text = term.utf8ToString()
        term_instance = Term(FIELDNAME, term_text)
        p_t[term_text] = int(reader.totalTermFreq(term_instance))

    # Close the reader and directory
    reader.close()
    directory.close()
    
    # Normalize the probabilities to ensure they sum up to 1
    total_prob = sum(list(p_t.values()))
    p_t = {term_text:cf/total_prob for term_text,cf in p_t.items()}

    return p_t


def generate_known_item_queries(p_t_dk):
    ''' Using the method which was demonstrated to be close to 
        English manual queries:
        Azzopardi et al. Building simulated queries for known-item topics:
        an analysis using six european languages. SIGIR 2007. '''
    
    # no. of queries generated per doc = 10% of the term vector length, with upper cap = 50 queries
    numQueries = min(round(0.1 * len(p_t_dk)), 50)
    
    # lmbda = 0.2     # lambda = 0.2 in the paper
    # p_t_theta_d = {term:(1-lmbda)*p_t_dk.get(term, 0) + lmbda*p_t[term] for term in p_t}
    
    # we take lambda = 0.0
    p_t_theta_d = p_t_dk
    
    mean_length = 4
    
    queries = []
    for _ in range(numQueries):
        query_length = round(np.random.poisson(mean_length))
        if query_length > 0:
            sampled_terms = random.choices(list(p_t_theta_d.keys()), weights=list(p_t_theta_d.values()), k=query_length)
            queries.append(' '.join(sampled_terms))
    
    return queries


def process_one_document(p_t_dk):
    return generate_known_item_queries(p_t_dk)


def process_documents(docs):
    # list of counters for this batch of documents
    batch_queries = {}
    
    for luceneDocid, p_t_dk in docs:
        batch_queries[luceneDocid] = process_one_document(p_t_dk)
        
    return batch_queries


def parallel_process_documents(corpus, num_workers, batch_size, numDocs):
    # to store docs and their respective queries
    total_queries = {}
    
    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        tasks = {}
        corpus_iter = iter(corpus)

        # Submit initial tasks
        num_tasks = min(num_workers, numDocs // batch_size + 1)
        for i in range(num_tasks):
            docs = list(itertools.islice(corpus_iter, batch_size))
            start_docid = docs[0][0]
            end_docid = docs[-1][0]
            future = executor.submit(process_documents, docs)
            tasks[future] = (start_docid, end_docid)

        with tqdm(total=numDocs) as progress_bar:
            while tasks:
                done, _ = wait(tasks, return_when=FIRST_COMPLETED)
                for future in done:
                    batch_queries = future.result()

                    # Merge the queries dict from this batch of docs to the global dict
                    total_queries.update(batch_queries)

                    del tasks[future]
                    progress_bar.update(batch_size)
                    
                    # Submit a new task
                    docs = list(itertools.islice(corpus_iter, batch_size))
                    if len(docs) > 0:
                        start_docid = docs[0][0]
                        end_docid = docs[-1][0]
                        future = executor.submit(process_documents, docs)
                        tasks[future] = (start_docid, end_docid)

    return total_queries


def main():
    FIELDNAME = 'CONTENT'       # Lucene index field name for content of the doc
    corpus_name = 'MSMARCO'
    index_path = '../../../../store/collection/indexed/msmarco-passage.notstored'   # Lucene index directory path

    # p_t distribution
    # p_t = compute_p_t_dist(index_path, FIELDNAME)
    
    # corpus doc generator object
    trec_corpus = MyCorpus(index_path, FIELDNAME)
    numDocs = trec_corpus.numDocs
    # start_docid, end_docid = 0, numDocs
    
    # specify batch_size for no. of docs to each worker thread
    batch_size = 1000

    num_workers = multiprocessing.cpu_count()-1     # You can adjust this based on your machine's capabilities
    total_queries = parallel_process_documents(trec_corpus, num_workers, batch_size=batch_size, numDocs=numDocs)
    
    # dump the known-item queries for each doc for performing retrievals on them
    output_dir = f'./{corpus_name}'
    # directory_name = f'{start_docid}-{end_docid}'
    # directory_path = os.path.join(output_dir, directory_name)
    os.makedirs(output_dir, exist_ok=True)
    with open(os.path.join(output_dir, f'queries_{corpus_name}.json'), 'w') as f:
        json.dump(total_queries, f)


if __name__=='__main__':
    main()