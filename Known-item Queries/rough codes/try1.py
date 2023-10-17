# lucene imports
import lucene
from org.apache.lucene.search import IndexSearcher
from org.apache.lucene.index import DirectoryReader, Term, PostingsEnum
from org.apache.lucene.store import FSDirectory, SimpleFSDirectory
from org.apache.lucene.util import BytesRefIterator
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
        # for luceneDocid in range(self.numDocs):
        for luceneDocid in [550]:
            term_vector = self.indexReader.getTermVector(luceneDocid, self.FIELDNAME).iterator()
            yield luceneDocid, self.indexReader.document(luceneDocid).get(self.FIELDNAME), term_vector
            

FIELDNAME = 'CONTENTS'       # Lucene index field name for content of the doc
index_path = '../../../wt10g/index_wt10g_cleaned'   # Lucene index directory path

# corpus doc generator object
wt10g_corpus = MyCorpus(index_path, FIELDNAME)

for i,returned in enumerate(wt10g_corpus):
    luceneDocid, doc, termVector = returned
    term_frequency_vector = {}
    print(luceneDocid)
    print(doc.strip())
    terms_enum = termVector
    for term in BytesRefIterator.cast_(terms_enum):
        term_text = term.utf8ToString()
        postings_enum = terms_enum.postings(None)
        while postings_enum.nextDoc() != PostingsEnum.NO_MORE_DOCS:
            freq = postings_enum.freq()
            term_frequency_vector[term_text] = freq
    print(term_frequency_vector)
    print()
    if i == 1:
        break