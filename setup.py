from setuptools import setup

setup(
    name='fmlpack',
    version='0.2.1',
    py_modules=['fmlpack'],
    package_dir={'': 'src'},
    entry_points={
        'console_scripts': [
            'fmlpack=fmlpack:main',
        ],
    },
    install_requires=[], # No mandatory dependencies for basic usage
    extras_require={
        'ignore': ['pathspec>=0.10.3'], # Optional for robust gitignore support
    },
    long_description=open('README.md', encoding='utf-8').read(),
    long_description_content_type='text/markdown',
    author='fedenunez',
    author_email='fedenunez+fmlpack@gmail.com',
    description='fmlpack: A tool to convert file trees to/from TEXT, ideal for working with LLM and a lot of files (using Filesystem Markup Language -FML-).',
    url='https://github.com/fedenunez/fmlpack', 
    license='MIT',
    classifiers=[
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Topic :: System :: Archiving :: Packaging',
        'Topic :: Text Processing :: Markup',
        'Environment :: Console',
    ],
    python_requires='>=3.6',
)
